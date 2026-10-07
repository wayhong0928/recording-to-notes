"""本機語音轉逐字稿（faster-whisper），輸出簡體的模型轉成台灣正體，多段錄音合併（計畫第 9 節）。

minutes transcribe <會議資料夾> 的流程：
1. 列出資料夾裡的錄音，依開始時間排序。
2. 每段分開轉錄，結果存到 _暫存/<錄音檔名>.轉錄.json。重跑時，模型、檔案大小、名單和術語都沒變的段落直接沿用。
3. 合併成 1_逐字稿.md。

用顯卡時載入或轉錄失敗（例如 GPU 套件缺檔），改用 CPU 重轉那一段，並告訴使用者原因。
"""
import json
import re
import time
from pathlib import Path

import opencc
from faster_whisper import WhisperModel

from minutes import check, merge, models, progress, recordings
from minutes.paths import TEMP

# evaluate.py 用的別名：模型沒下載到程式資料夾時，交給 faster-whisper 從 Hugging Face 快取抓
MODEL_ALIASES = {name: m.repo for name, m in models.MODELS.items()}
PROGRESS_EVERY = 30  # 秒


class TranscribeError(Exception):
    pass


def load_model(name: str, device: str) -> tuple[WhisperModel, str]:
    if name in models.MODELS and models.is_downloaded(name):
        src = str(models.path(name))
    else:
        src = MODEL_ALIASES.get(name, name)
    if device == "cuda":
        check.add_gpu_dlls()
        return WhisperModel(src, device="cuda", compute_type="float16"), "cuda"
    return WhisperModel(src, device="cpu", compute_type="int8"), "cpu"


_S2TW = opencc.OpenCC("s2tw")
# OpenCC 的詞庫把「多只」當成量詞（多隻貓），「最多只能」會變成「最多隻能」。官方 opencc 套件也一樣。
# 前面是數字的（一隻、幾隻）才當量詞，不改回來；「這只能」在會議裡比「這隻（動物）能」常見，改回只
_ZHI_FIX = re.compile(r"(?<![一二兩三四五六七八九十幾半])隻(?=[能有是要好會剩])")


def to_traditional(text: str) -> str:
    """簡體轉台灣正體。只轉字形；s2twp 會連詞彙一起換（例如 信息→資訊），會改壞術語。"""
    return _ZHI_FIX.sub("只", _S2TW.convert(text))


def transcribe_segments(model: WhisperModel, audio: Path, prompt: str | None = None, on_progress=None,
                        simplified: bool = True):
    """回傳 ([(起, 迄, 正體文字)], info)。evaluate.py 也用這個，確保評測跟實際使用的參數一致。
    simplified：模型輸出簡體字，要轉正體（用 models.outputs_simplified 判斷）。"""
    segments, info = model.transcribe(
        str(audio), language="zh", initial_prompt=prompt,
        vad_filter=True, beam_size=5,
    )
    conv = to_traditional if simplified else str
    out = []
    for s in segments:
        out.append((s.start, s.end, conv(s.text.strip())))
        if on_progress:
            on_progress(s.end, info.duration)
    return out, info


def cache_path(rec: recordings.Recording) -> Path:
    return rec.path.parent / TEMP / f"{rec.path.name}.轉錄.json"


def cache_key(rec: recordings.Recording, model: str, terms: list[str]) -> dict:
    return {"model": model, "size": rec.path.stat().st_size, "terms": terms}


def load_cache(rec: recordings.Recording, key: dict) -> list | None:
    f = cache_path(rec)
    if not f.is_file():
        return None
    try:
        data = json.loads(f.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if data.get("key") != key:
        return None
    return [tuple(s) for s in data["segments"]]


def save_cache(rec: recordings.Recording, key: dict, segs: list, device: str, elapsed: float) -> None:
    f = cache_path(rec)
    f.parent.mkdir(exist_ok=True)
    tmp = f.with_suffix(".tmp")
    data = {"key": key, "device": device, "elapsed": round(elapsed, 1), "duration": rec.duration,
            "segments": [list(s) for s in segs]}
    tmp.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    tmp.replace(f)  # 寫完才換名，中斷時不會留下半份


class Engine:
    """需要時才載入模型；顯卡失敗時改用 CPU。"""

    def __init__(self, model: str, device: str, log):
        self.model_name, self.device, self.log = model, device, log
        self.model = None
        self.fallback_reason = ""
        self.simplified = models.outputs_simplified(model)

    def _load(self) -> None:
        models.ensure(self.model_name, self.log)
        try:
            self.model, self.device = load_model(self.model_name, self.device)
        except (RuntimeError, OSError, ValueError) as e:
            if self.device != "cuda":
                raise
            self._to_cpu(e)

    def _to_cpu(self, e: Exception) -> None:
        self.fallback_reason = f"顯卡用不了（{str(e)[:200]}），改用 CPU"
        self.log(self.fallback_reason + "。")
        self.device = "cpu"
        self.model, _ = load_model(self.model_name, "cpu")

    def count_tokens(self, text: str) -> int:
        if self.model is None:
            self._load()
        # faster-whisper 會在提示文字前面加一個空白再編碼
        return len(self.model.hf_tokenizer.encode(" " + text, add_special_tokens=False).ids)

    def run(self, audio: Path, prompt: str | None, on_progress) -> list:
        if self.model is None:
            self._load()
        try:
            return transcribe_segments(self.model, audio, prompt, on_progress, self.simplified)[0]
        except (RuntimeError, OSError) as e:
            if self.device != "cuda":
                raise
            self._to_cpu(e)
            return transcribe_segments(self.model, audio, prompt, on_progress, self.simplified)[0]


def run(folder: Path, model: str = models.DEFAULT, device: str = "auto", log=print, engine=None,
        probe_fn=recordings.probe, window: bool = False) -> dict:
    """window：有段落要轉時開進度視窗。進度檔寫好才開，視窗不會讀到上一輪的結果。"""
    if not folder.is_dir():
        raise TranscribeError(f"找不到會議資料夾：{folder}")
    recs = [recordings.describe(p, probe_fn) for p in recordings.audio_files(folder)]
    if bad := [r for r in recs if r.error]:
        raise TranscribeError("；".join(f"{r.path.name}：{r.error}" for r in bad))
    recs = recordings.order(recs)
    if not recs:
        raise TranscribeError(f"會議資料夾裡沒有錄音：{folder}")

    terms = merge.read_terms(folder)
    todo = [r for r in recs if load_cache(r, cache_key(r, model, terms)) is None]
    log(f"共 {len(recs)} 段錄音，{len(recs) - len(todo)} 段之前轉過，這次要轉 {len(todo)} 段。")

    tracker = progress.Tracker(folder, sum(r.duration for r in recs), len(recs))
    if window and todo:
        progress.launch_window(folder)
    try:
        result = _run(folder, recs, todo, terms, model, device, log, engine, tracker)
    except BaseException as e:
        tracker.fail("轉錄被中斷" if isinstance(e, KeyboardInterrupt) else f"{e.__class__.__name__}：{str(e)[:300]}")
        raise
    tracker.finish()
    return result


def _run(folder: Path, recs: list, todo: list, terms: list[str], model: str, device: str, log, engine,
         tracker: progress.Tracker) -> dict:
    prompt, dropped, why = None, [], ""
    if todo:
        chosen, why = check.pick_device(device)
        engine = engine or Engine(model, chosen, log)
        log(f"模型 {model}，{why}。")
        if terms:
            prompt, dropped = merge.build_prompt(terms, engine.count_tokens)
            if dropped:
                log(f"名單和術語太長，後面 {len(dropped)} 行沒放進提示文字：{'、'.join(dropped)}")

    parts, timings, before = [], [], 0.0  # before：前面幾段的總長，算整場進度用
    for i, r in enumerate(recs, 1):
        key = cache_key(r, model, terms)
        segs = load_cache(r, key)
        if segs is None:
            log(f"第 {i}／{len(recs)} 段開始轉錄：{r.path.name}（長 {recordings.fmt_duration(r.duration)}）")
            tracker.start_part(i, before)
            last = [time.monotonic()]

            def on_progress(done: float, total: float, i=i, last=last, before=before) -> None:
                tracker.update(before + done)
                if time.monotonic() - last[0] >= PROGRESS_EVERY:
                    last[0] = time.monotonic()
                    log(f"第 {i}／{len(recs)} 段：已轉 {recordings.fmt_duration(done)} ／ {recordings.fmt_duration(total)}")

            t0 = time.monotonic()
            segs = engine.run(r.path, prompt, on_progress)
            elapsed = time.monotonic() - t0
            save_cache(r, key, segs, engine.device, elapsed)
            timings.append({"file": r.path.name, "seconds": round(elapsed, 1),
                            "ratio": round(elapsed / r.duration, 2) if r.duration else None})
            log(f"第 {i}／{len(recs)} 段轉完，花了 {recordings.fmt_duration(elapsed)}。")
        parts.append((r, segs))
        before += r.duration

    devices = {json.loads(cache_path(r).read_text(encoding="utf-8"))["device"] for r in recs}
    used = "cuda" if devices == {"cuda"} else "cpu"
    out = folder / merge.TRANSCRIPT_FILE
    tmp = out.with_suffix(".tmp")
    tmp.write_text(merge.render(folder, parts, model, used), encoding="utf-8")
    tmp.replace(out)
    log(f"逐字稿：{out}")
    return {
        "ok": True, "transcript": str(out), "model": model, "device": used,
        "device_note": why, "fallback": engine.fallback_reason if todo else "",
        "parts": [recordings.to_dict(r) for r in recs], "transcribed": timings,
        "prompt_dropped": dropped,
    }
