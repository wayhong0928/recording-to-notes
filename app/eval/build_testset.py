"""把測試集腳本合成成一個音檔，並寫出每行的起訖時間（metadata）。

用法（在 app\\ 底下）：uv run python eval\\build_testset.py eval\\testset\\meeting_01.txt
輸出：eval\\out\\testset\\<名稱>\\audio.wav、meta.json（out\\ 不進 git）
"""
import argparse
import json
import subprocess
import sys
import wave
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from textnorm import parse_script  # noqa: E402

VOICES = {"A": "Yating", "B": "Zhiwei", "C": "Hanhan"}
LEAD_IN = 1.0      # 開頭靜音秒數
GAP_SAME = 0.5     # 同一人連續兩句之間
GAP_SWITCH = 0.9   # 換人說話之間


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("script")
    args = ap.parse_args()

    script = Path(args.script)
    here = Path(__file__).resolve().parent
    out_dir = here / "out" / "testset" / script.stem
    seg_dir = out_dir / "lines"
    out_dir.mkdir(parents=True, exist_ok=True)

    lines = parse_script(script)
    jobs = [{"id": f"{ln.n:03d}", "voice": VOICES[ln.speaker], "text": ln.text} for ln in lines]
    job_file = out_dir / "jobs.json"
    job_file.write_text(json.dumps(jobs, ensure_ascii=False), encoding="utf-8")
    subprocess.run(
        ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File",
         str(here / "synth_tts.ps1"), "-JobFile", str(job_file), "-OutDir", str(seg_dir)],
        check=True,
    )

    params, chunks, meta_lines = None, [], []
    t, prev_speaker = LEAD_IN, None
    for ln in lines:
        with wave.open(str(seg_dir / f"{ln.n:03d}.wav"), "rb") as w:
            p = (w.getnchannels(), w.getsampwidth(), w.getframerate())
            params = params or p
            if p != params:
                raise SystemExit(f"第 {ln.n} 行的音訊格式 {p} 跟前面 {params} 不同")
            frames = w.readframes(w.getnframes())
            dur = w.getnframes() / w.getframerate()
        gap = LEAD_IN if prev_speaker is None else (GAP_SAME if ln.speaker == prev_speaker else GAP_SWITCH)
        silence = b"\x00" * (int(gap * params[2]) * params[0] * params[1])
        if prev_speaker is not None:
            t += gap
        chunks += [silence, frames]
        meta_lines.append({"n": ln.n, "speaker": ln.speaker, "voice": VOICES[ln.speaker],
                           "start": round(t, 2), "end": round(t + dur, 2), "text": ln.text})
        t += dur
        prev_speaker = ln.speaker

    audio = out_dir / "audio.wav"
    with wave.open(str(audio), "wb") as w:
        w.setnchannels(params[0])
        w.setsampwidth(params[1])
        w.setframerate(params[2])
        w.writeframes(b"".join(chunks))
    meta = {"script": script.name, "audio": audio.name, "duration": round(t, 2),
            "sample_rate": params[2], "lines": meta_lines}
    (out_dir / "meta.json").write_text(json.dumps(meta, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"done: {audio} ({t:.1f}s, {len(lines)} lines, {params[2]} Hz)")


if __name__ == "__main__":
    main()
