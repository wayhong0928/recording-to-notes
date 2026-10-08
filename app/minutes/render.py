"""md 轉 Word（計畫第 10 節），加上 Word 指紋記錄。

輸入是會議資料夾，讀 2_會議紀錄.md，輸出「2_會議紀錄_yyyymmddhhmmss.docx」，舊檔不刪；
同一秒內重跑時檔名加 _2、_3。每次產生都把檔案的 SHA-256 記到 _暫存/word_紀錄.json，
之後拿來判斷使用者有沒有在 Word 裡改過。最新一版被改過時只提醒、照樣產生（決定第 24 條：
使用者自己把 Word 的修改貼回對話，程式不讀回 Word）。

md 的寫法見 templates/content/會議紀錄格式.md，規則：
- 開頭幾行是「欄位：值」，欄位名稱固定六個，值可以空白；全形、半形冒號都可以，
  欄位名前後可以有 - 或 **；值只能寫一行，換行的部分會被忽略
- 段落標題是「會議內容」「決議事項」「討論事項」，前面有沒有 # 或 ** 都可以，但不能縮排
- 會議內容、決議事項：每項一行，開頭是 1. 1、 1) 或 - ；沒有編號的行接到上一項後面（前面沒有項目就自成一項）；編號由範本整份重編，md 裡的編號跳號沒關係
- 討論事項：
    編號開頭的行（有沒有縮排都算）  → 一題詢問
    縮排（空白、tab、全形空白）或 - 開頭的行 → 接在上一題底下（回覆、補充、結論）
    其他的行                       → 議題標題
  所以回覆行一定要縮排，不然會被當成議題標題。「3.5 倍」這種小數不算編號。
  稱呼和「詢問／回覆」這些字照 md 原文放進 Word，範本不改字；題號由程式整份重編
- & < > 這些符號會照原樣放進 Word（render 時開了 autoescape）
"""
import hashlib
import json
import os
import re
import subprocess
import sys
from datetime import datetime
from pathlib import Path

from minutes import paths
from minutes.paths import TEMP

MINUTES_FILE = "2_會議紀錄.md"
RECORD = "word_紀錄.json"
WORD_TEMPLATE = "中性範例.docx"

FIELDS = {"專案名稱": "project", "會議名稱": "meeting", "會議地點": "location",
          "會議時間": "time", "與會人員": "attendees", "記錄人": "recorder"}
SECTIONS = {"會議內容": "contents", "決議事項": "decisions", "討論事項": "discussions"}

FIELD_RE = re.compile(r"^[-*]?\s*(%s)\s*[：:]\s*(.*)$" % "|".join(FIELDS))
# 編號後面緊接數字的不算（例如「3.5 倍」）
NUMBERED_RE = re.compile(r"^\d+\s*[.、)）](?!\d)\s*(.*)$")
INDENT = (" ", "\t", "　")
BULLET_RE = re.compile(r"^[-*]\s+(.*)$")


class RenderError(Exception):
    pass


def clean(text: str) -> str:
    """去掉 md 的粗體記號和前後空白。"""
    return text.replace("**", "").strip()


def section_name(line: str) -> str | None:
    """這行如果是段落標題，回傳對應的 key；不是就回傳 None。"""
    name = clean(line.lstrip("#").strip().strip("*：:"))
    return SECTIONS.get(name)


def parse(md: str) -> dict:
    data = {key: "" for key in FIELDS.values()}
    data.update(contents=[], decisions=[], discussions=[])
    current = None  # 目前在哪個段落

    for raw in md.splitlines():
        if not raw.strip():
            continue
        indented = raw.startswith(INDENT)
        key = None if indented else section_name(raw)
        if key:
            current = key
            continue

        if current is None:
            m = FIELD_RE.match(clean(raw))
            if m:
                data[FIELDS[m.group(1)]] = clean(m.group(2))
            continue

        line = clean(raw)
        if current in ("contents", "decisions"):
            m = NUMBERED_RE.match(line) or BULLET_RE.match(line)
            if m:
                data[current].append(clean(m.group(1)))
            elif data[current]:
                # 沒有編號的行當成上一項的續行
                data[current][-1] += line
            else:
                data[current].append(line)
            continue

        # 討論事項
        topics = data["discussions"]
        numbered = NUMBERED_RE.match(line)
        bullet = BULLET_RE.match(line)
        last_item = topics[-1]["items"][-1] if topics and topics[-1]["items"] else None

        if (indented or bullet) and last_item is not None and not numbered:
            last_item["follow"].append(clean(bullet.group(1)) if bullet else line)
        elif numbered:
            if not topics:
                topics.append({"title": "", "items": []})
            topics[-1]["items"].append({"ask": clean(numbered.group(1)), "follow": []})
        else:
            topics.append({"title": line, "items": []})

    no = 0
    for topic in data["discussions"]:
        for item in topic["items"]:
            no += 1
            item["no"] = no
    return data


# ---- Word 指紋 ----

def sha256(path: Path) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def record_path(folder: Path) -> Path:
    return Path(folder) / TEMP / RECORD


def load_record(folder: Path) -> dict:
    p = record_path(folder)
    if p.exists():
        return json.loads(p.read_text(encoding="utf-8"))
    return {"files": []}


def save_record(folder: Path, rec: dict) -> None:
    p = record_path(folder)
    p.parent.mkdir(exist_ok=True)
    p.write_text(json.dumps(rec, ensure_ascii=False, indent=1), encoding="utf-8")


def remember(folder: Path, docx: Path) -> None:
    rec = load_record(folder)
    rec["files"].append({"name": docx.name, "sha256": sha256(docx),
                         "time": datetime.now().isoformat(timespec="seconds")})
    save_record(folder, rec)


def status(folder: Path) -> dict:
    """最新一版（還在資料夾裡的）Word 在產生之後有沒有被改過。"""
    folder = Path(folder)
    existing = [e for e in load_record(folder)["files"] if (folder / e["name"]).exists()]
    if not existing:
        return {"latest": None, "generated": None, "edited": False, "modified": None}
    latest = existing[-1]
    p = folder / latest["name"]
    edited = sha256(p) != latest["sha256"]
    modified = datetime.fromtimestamp(p.stat().st_mtime).isoformat(timespec="seconds") if edited else None
    return {"latest": latest["name"], "generated": latest["time"], "edited": edited, "modified": modified}


def status_text(st: dict) -> str:
    if st["latest"] is None:
        return "這個資料夾還沒有產生過 Word。"
    if st["edited"]:
        return f"{st['latest']}（{st['generated']} 產生）在產生之後被改過，最後修改時間 {st['modified']}。"
    return f"{st['latest']}（{st['generated']} 產生）之後沒有被改過。"


# ---- 產生 ----

def template_path() -> Path:
    return paths.templates() / "word" / WORD_TEMPLATE


def output_path(folder: Path, now: datetime) -> Path:
    stem = f"{Path(MINUTES_FILE).stem}_{now:%Y%m%d%H%M%S}"
    out, n = folder / f"{stem}.docx", 2
    while out.exists():
        out, n = folder / f"{stem}_{n}.docx", n + 1
    return out


def open_file(path: Path) -> tuple[bool, str]:
    """用預設程式打開 docx。打不開不算失敗，回傳說明。"""
    try:
        if sys.platform == "win32":
            os.startfile(path)  # noqa: S606
        elif sys.platform == "darwin":
            subprocess.run(["open", str(path)], check=True, capture_output=True)
        else:
            subprocess.run(["xdg-open", str(path)], check=True, capture_output=True)
    except (OSError, subprocess.CalledProcessError):
        return False, f"沒辦法自動打開 Word（這台可能沒裝 Word），檔案在 {path}"
    return True, "已經用 Word 打開"


def render(folder: Path, open_word: bool = True) -> dict:
    from docxtpl import DocxTemplate

    folder = Path(folder)
    md = folder / MINUTES_FILE
    if not md.is_file():
        raise RenderError(f"找不到 {MINUTES_FILE}：{md}")
    tpl_path = template_path()
    if not tpl_path.is_file():
        raise RenderError(f"找不到 Word 公版：{tpl_path}。重跑安裝檔會補回來。")

    before = status(folder)
    data = parse(md.read_text(encoding="utf-8-sig"))
    tpl = DocxTemplate(tpl_path)
    tpl.render(data, autoescape=True)
    out = output_path(folder, datetime.now())
    tpl.save(out)
    remember(folder, out)

    opened, open_note = open_file(out) if open_word else (False, "沒有打開 Word（--no-open）")
    return {
        "ok": True, "docx": str(out), "opened": opened, "open_note": open_note,
        "previous": before["latest"], "previous_edited": before["edited"],
        "counts": {"contents": len(data["contents"]), "decisions": len(data["decisions"]),
                   "topics": len(data["discussions"]),
                   "questions": sum(len(t["items"]) for t in data["discussions"])},
    }


def render_text(result: dict) -> str:
    lines = []
    if result["previous_edited"]:
        lines.append(f"提醒：上一版 {result['previous']} 在產生之後被改過，新版不會包含 Word 裡改的內容。")
    c = result["counts"]
    lines.append(f"已產生 {Path(result['docx']).name}（會議內容 {c['contents']} 項、決議 {c['decisions']} 項、"
                 f"討論 {c['topics']} 個議題 {c['questions']} 題）")
    lines.append(result["open_note"])
    return "\n".join(lines)
