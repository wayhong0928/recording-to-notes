"""名單和術語轉成提示文字、多段逐字稿合併（計畫第 9 節）。

合併時把每段的時間戳換成時鐘時間，段落之間插一行「第 2 段，14:31:05 開始，和上一段隔 3 秒」。
"""
from datetime import date, timedelta
from pathlib import Path

from minutes.recordings import Recording, clock, fmt_duration, gap_text, start_text

TERMS_FILE = "0_名單與術語.txt"
TRANSCRIPT_FILE = "1_逐字稿.md"
# Whisper 的提示文字最多 448／2－1 個 token；faster-whisper 超過時會從前面截掉，所以自己先從後面截
PROMPT_TOKENS = 223


def read_terms(folder: Path) -> list[str]:
    f = folder / TERMS_FILE
    if not f.is_file():
        return []
    lines = f.read_text(encoding="utf-8-sig").splitlines()
    return [s for s in (ln.strip() for ln in lines) if s and not s.startswith("#")]


def build_prompt(terms: list[str], count_tokens) -> tuple[str | None, list[str]]:
    """回傳（提示文字、放不下被截掉的行）。整行整行截，不把一個名字切成兩半。"""
    kept = list(terms)
    while kept and count_tokens("、".join(kept)) > PROMPT_TOKENS:
        kept.pop()
    return ("、".join(kept) or None), terms[len(kept):]


def part_heading(i: int, r: Recording, base: date) -> str:
    text = f"第 {i} 段，{start_text(r.start, base)}"
    if gap := gap_text(r):
        text += f"，{gap}"
    return f"{text}（{r.path.name}，長 {fmt_duration(r.duration)}）"


def render(folder: Path, parts: list[tuple[Recording, list]], model: str, device: str) -> str:
    """parts 是 [(錄音, [(起, 迄, 文字), ...])]，已經依開始時間排好。"""
    total = fmt_duration(sum(r.duration for r, _ in parts))
    lines = [
        "# 逐字稿",
        "",
        f"會議資料夾：{folder.name}",
        f"模型：{model}（{'顯卡' if device == 'cuda' else 'CPU'}）",
        f"錄音：{len(parts)} 段，共 {total}",
        "",
        "自動轉錄，沒有校對，專有名詞可能聽錯。方括號裡是時鐘時間，過了午夜的標「（隔天）」。",
    ]
    notes = []
    for i, (r, _) in enumerate(parts, 1):
        if not r.certain:
            notes.append(f"- 第 {i} 段的開始時間來自{r.source}，不一定準。")
        if "overlap" in r.flags:
            notes.append(f"- 第 {i} 段和前面的錄音時間重疊，開始時間可能不準。")
    if notes:
        lines += ["", *notes]
    base = parts[0][0].start.date()
    for i, (r, segs) in enumerate(parts, 1):
        lines += ["", f"## {part_heading(i, r, base)}", ""]
        if not segs:
            lines.append("（這段沒有聽到說話）")
        lines += [f"- [{clock(r.start + timedelta(seconds=start), base)}] {text}" for start, _, text in segs]
    return "\n".join(lines) + "\n"
