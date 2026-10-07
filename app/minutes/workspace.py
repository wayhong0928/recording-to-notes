"""建工作區（計畫第 5 節、第 8 節安裝第 5 步）。

把 workspace_template/ 複製到工作區，skill 裡的 {{MINUTES}} 換成 minutes 程式的完整路徑，
再把內容公版（整理規則.md、問答式.md）放進 skill 資料夾，skill 用相對路徑讀。
重跑時 skill 照新版覆蓋（使用者改過的整理規則也會被換掉，先備份成 .舊.md），
「錄音放這裡」「會議」裡的東西不動。
"""
import shutil
import subprocess
import sys
from pathlib import Path

from minutes import paths

PLACEHOLDER = "{{MINUTES}}"
SKILL_DIR = Path(".claude") / "skills" / "會議紀錄"
CONTENT_FILES = ("整理規則.md", "問答式.md")


def template_dir() -> Path:
    return paths.app_root() / "workspace_template"


def minutes_command() -> str:
    """目前這個環境的 minutes 執行檔，用正斜線，Bash 和 PowerShell 都認得。"""
    scripts = Path(sys.executable).parent
    exe = scripts / ("minutes.exe" if sys.platform == "win32" else "minutes")
    return exe.as_posix()


def setup(target: Path | None = None, minutes: str | None = None) -> dict:
    target = Path(target) if target else paths.workspace()
    minutes = minutes or minutes_command()
    for name in (paths.INBOX, paths.MEETINGS):
        (target / name).mkdir(parents=True, exist_ok=True)

    written = []
    src_root = template_dir()
    for src in sorted(p for p in src_root.rglob("*") if p.is_file()):
        dst = target / src.relative_to(src_root)
        dst.parent.mkdir(parents=True, exist_ok=True)
        dst.write_text(src.read_text(encoding="utf-8").replace(PLACEHOLDER, minutes), encoding="utf-8")
        written.append(dst)

    skill = target / SKILL_DIR
    for name in CONTENT_FILES:
        src, dst = paths.templates() / "content" / name, skill / name
        if dst.exists() and dst.read_bytes() != src.read_bytes():
            shutil.copy2(dst, dst.with_suffix(".舊.md"))
        shutil.copy2(src, dst)
        written.append(dst)

    if sys.platform == "win32":
        subprocess.run(["attrib", "+h", str(target / ".claude")], capture_output=True)
    return {"workspace": str(target), "minutes": minutes, "files": [str(p) for p in written]}
