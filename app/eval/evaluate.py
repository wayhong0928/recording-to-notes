"""用測試集比較各模型：混合錯誤率（MER）、關鍵資訊正確率、多出的否定詞、耗時。

先跑 eval\\build_testset.py 產生音檔，再在 app\\ 底下跑：
    uv run python eval\\evaluate.py meeting_01 [--models large-v3 large-v3-turbo breeze] [--reuse]
--reuse：沿用已存的轉錄結果，只重算分數。輸出在 eval\\out\\testset\\<名稱>\\。
"""
import argparse
import gc
import json
import sys
import time
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))
from textnorm import NEGATIONS, NUMERAL_CHARS, align, edit_align, normalize, parse_script, reference_tokens  # noqa: E402

CATS = {"neg": "否定詞", "num": "數字", "date": "日期時間", "name": "人名", "en": "英文"}


def fmt(sec: float) -> str:
    m, s = divmod(int(sec), 60)
    return f"{m:02d}:{s:02d}"


def run_model(name: str, audio: Path, device: str) -> dict:
    from minutes.models import outputs_simplified
    from minutes.transcribe import load_model, transcribe_segments
    model, dev = load_model(name, device)
    t0 = time.time()
    segs, _ = transcribe_segments(model, audio, simplified=outputs_simplified(name))
    elapsed = time.time() - t0
    del model
    gc.collect()
    return {"model": name, "device": dev, "elapsed": round(elapsed, 1),
            "segments": [{"start": round(a, 2), "end": round(b, 2), "text": t} for a, b, t in segs]}


def score(hyp: dict, ref: list[str], line_of: list[int], keys: list, starts: dict) -> dict:
    hyp_tok = normalize("".join(s["text"] for s in hyp["segments"]))
    # 錯誤率用純最小編輯距離；關鍵資訊與否定詞用錨定對齊（見 textnorm.align 的說明）
    c = Counter(op for op, _, _ in edit_align(ref, hyp_tok))
    ops = align(ref, hyp_tok)
    segs = hyp["segments"]
    repeats = [s for prev, s in zip(segs, segs[1:]) if s["text"] and s["text"] == prev["text"]]
    pos ={i: k for k, (_, i, _) in enumerate(ops) if i is not None}

    key_res = []
    for a, b, cat, text, n in keys:
        if a == b:
            continue
        lo, hi = pos[a], pos[b - 1] + 1
        span = ops[lo:hi]
        ok = all(op == "eq" for op, _, _ in span)
        if cat in ("num", "date"):
            # 緊貼在數字前後多出來的數字字（40→140、9折→19折）也算錯
            for k in (lo - 1, hi):
                if 0 <= k < len(ops) and ops[k][0] == "ins" and hyp_tok[ops[k][2]] in NUMERAL_CHARS:
                    ok = False
                    span = ops[min(k, lo):max(k + 1, hi)]
        key_res.append({"cat": cat, "text": text, "line": n, "time": starts[n], "ok": ok,
                        "got": "".join(hyp_tok[j] for _, _, j in span if j is not None)})

    # 模型多聽出來的否定詞（參考答案沒有），最危險：意思會整個相反
    extra_neg, last_ref = [], 0
    for op, i, j in ops:
        if i is not None:
            last_ref = i
        if op in ("ins", "sub") and hyp_tok[j] in NEGATIONS:
            n = line_of[last_ref]
            extra_neg.append({"line": n, "time": starts[n], "got": hyp_tok[j],
                              "ref": ref[i] if op == "sub" else ""})

    return {"model": hyp["model"], "device": hyp["device"], "elapsed": hyp["elapsed"],
            "n_ref": len(ref), "sub": c["sub"], "del": c["del"], "ins": c["ins"],
            "mer": (c["sub"] + c["del"] + c["ins"]) / len(ref), "keys": key_res, "extra_neg": extra_neg,
            "repeats": [{"time": s["start"], "text": s["text"]} for s in repeats]}


def report(name: str, meta: dict, results: list[dict], lines_text: dict) -> str:
    out = [f"# 評測報告：{name}", "",
           f"- 音檔長度 {fmt(meta['duration'])}，{len(meta['lines'])} 句，參考答案 {results[0]['n_ref']} 個 token",
           "- MER＝(替換＋刪除＋插入)／參考 token 數。中文一字一個 token，英文連續字母一個 token，數字轉成中文讀法再比，去掉標點與空白；不做簡轉繁，轉錯的字（例如只→隻）算錯",
           "- 關鍵資訊：腳本裡用 {文字|類別} 標記的片段，片段內每個 token 都對才算對",
           "- 重複段落：跟前一段文字完全相同的段落數（模型幻覺的常見形式）；多出的否定詞包含重複段落裡的", ""]
    head = ("| 模型 | MER | 替換／刪除／插入 | 關鍵資訊 | " + " | ".join(CATS.values())
            + " | 多出的否定詞 | 重複段落 | 耗時 |")
    out += [head, "|" + "---|" * (head.count("|") - 1)]
    for r in results:
        per = []
        for cat in CATS:
            ks = [k for k in r["keys"] if k["cat"] == cat]
            per.append(f"{sum(k['ok'] for k in ks)}/{len(ks)}")
        ok = sum(k["ok"] for k in r["keys"])
        rtf = r["elapsed"] / meta["duration"]
        out.append(f"| {r['model']} | {r['mer']:.1%} | {r['sub']}／{r['del']}／{r['ins']} | {ok}/{len(r['keys'])} | "
                   + " | ".join(per) + f" | {len(r['extra_neg'])} | {len(r['repeats'])} | {r['elapsed']:.0f} 秒（{r['device']}，即時率 {rtf:.2f}） |")
    for r in results:
        out += ["", f"## {r['model']} 錯的關鍵資訊", ""]
        bad = [k for k in r["keys"] if not k["ok"]]
        out += [f"- [{fmt(k['time'])}] 第 {k['line']} 句 {CATS[k['cat']]}「{k['text']}」→ 轉成「{k['got'] or '（漏掉）'}」"
                f"｜原句：{lines_text[k['line']]}" for k in bad] or ["- 沒有"]
        if r["extra_neg"]:
            out += ["", "多出的否定詞："]
            out += [f"- [{fmt(e['time'])}] 第 {e['line']} 句多了「{e['got']}」" + (f"（原本是「{e['ref']}」）" if e["ref"] else "")
                    for e in r["extra_neg"]]
        if r["repeats"]:
            out += ["", "重複段落："]
            out += [f"- [{fmt(s['time'])}] {s['text']}" for s in r["repeats"]]
    return "\n".join(out) + "\n"


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("testset", help="測試集名稱，例如 meeting_01")
    ap.add_argument("--models", nargs="+", default=["large-v3", "large-v3-turbo", "breeze"])
    ap.add_argument("--device", choices=["cpu", "cuda"], default="cuda")
    ap.add_argument("--reuse", action="store_true")
    args = ap.parse_args()

    ts_dir = ROOT / "out" / "testset" / args.testset
    meta = json.loads((ts_dir / "meta.json").read_text(encoding="utf-8"))
    lines = parse_script(ROOT / "testset" / f"{args.testset}.txt")
    ref, line_of, keys = reference_tokens(lines)
    starts = {ln["n"]: ln["start"] for ln in meta["lines"]}

    results = []
    for name in args.models:
        hyp_file = ts_dir / f"hyp_{name.replace('/', '_')}.json"
        if args.reuse and hyp_file.exists():
            hyp = json.loads(hyp_file.read_text(encoding="utf-8"))
        else:
            hyp = run_model(name, ts_dir / meta["audio"], args.device)
            hyp_file.write_text(json.dumps(hyp, ensure_ascii=False, indent=1), encoding="utf-8")
        results.append(score(hyp, ref, line_of, keys, starts))
        print(f"{name}: MER {results[-1]['mer']:.1%}, {hyp['elapsed']}s", flush=True)

    text = report(args.testset, meta, results, {ln.n: ln.text for ln in lines})
    (ts_dir / "report.md").write_text(text, encoding="utf-8")
    print(text)


if __name__ == "__main__":
    main()
