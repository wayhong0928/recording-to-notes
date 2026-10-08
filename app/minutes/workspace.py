"""建工作區（計畫第 5 節、第 8 節安裝第 5 步）。

把 workspace_template/ 複製到工作區，skill 裡的 {{MINUTES}} 換成 minutes 程式的完整路徑，
再把內容公版（整理規則.md、會議紀錄格式.md）放進 skill 資料夾，skill 用相對路徑讀；
給使用者開會前用的空白範本（會議紀錄範本.md）放在工作區最上層。
重跑時這些都照新版覆蓋（使用者改過的先備份成 .舊.md），
「錄音放這裡」「會議」裡的東西不動。
「改過」是指跟上次安裝的內容不同：每次安裝把裝進去的雜湊記在 skill 資料夾的 .installed.json，
沒有這份紀錄的（v0.2.0 以前裝的）改跟發布過的版本比。
"""
import hashlib
import json
import shutil
import subprocess
import sys
from pathlib import Path

from minutes import paths

PLACEHOLDER = "{{MINUTES}}"
SKILL_DIR = Path(".claude") / "skills" / "會議紀錄"
CONTENT_FILES = ("整理規則.md", "會議紀錄格式.md")
BLANK = "會議紀錄範本.md"
# v0.3.0 以前的格式公版叫問答式.md。沒改過的直接刪，改過的備份成 .舊.md
LEGACY = "問答式.md"
MANIFEST = ".installed.json"
# 還沒有 .installed.json 的版本裝進去的內容（換行統一成 LF 算）
RELEASED_SHA256 = {
    "整理規則.md": {
        "cf7ea8952d06989f40519bc8b33b103ada39081892c1a1fc41271079ad32a00a",  # v0.1.0、v0.2.0
        "b85e09a608b33ab8f8f816aeaf4673fb84fb0eb1f2be7c684bdd9b1905feba40",  # 沒發布的開發版
    },
    LEGACY: {
        "9e4a5c26d900e4c46945685441a2fbd0736781d07e21db391ae6b7047cb9de55",  # v0.1.0、v0.2.0
        "bcf7b19db486f890910c93602c56820b218a087f948c0ca39b3a545c37966bd6",  # 沒發布的開發版
    },
}


def template_dir() -> Path:
    return paths.app_root() / "workspace_template"


def minutes_command() -> str:
    """目前這個環境的 minutes 執行檔，用正斜線，Bash 和 PowerShell 都認得。"""
    scripts = Path(sys.executable).parent
    exe = scripts / ("minutes.exe" if sys.platform == "win32" else "minutes")
    return exe.as_posix()


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes().replace(b"\r\n", b"\n")).hexdigest()


def edited(path: Path, installed: dict) -> bool:
    """跟上次裝進去的內容（或發布過的版本）都不同，就算使用者改過。"""
    known = RELEASED_SHA256.get(path.name, set()) | {installed.get(path.name)}
    return digest(path) not in known


def backup(path: Path) -> Path:
    dst = path.with_suffix(".舊.md")
    shutil.copy2(path, dst)
    return dst


def replace_file(src: Path, dst: Path, installed: dict) -> Path | None:
    """用新版覆蓋；使用者改過的先備份成 .舊.md，回傳備份的位置。"""
    saved = None
    if dst.is_file() and digest(dst) != digest(src) and edited(dst, installed):
        saved = backup(dst)
    shutil.copy2(src, dst)
    return saved


def retire_legacy(skill: Path, installed: dict) -> Path | None:
    old = skill / LEGACY
    if not old.is_file():
        return None
    saved = backup(old) if edited(old, installed) else None
    old.unlink()
    return saved


def load_manifest(skill: Path) -> dict:
    try:
        record = json.loads((skill / MANIFEST).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return record if isinstance(record, dict) else {}


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

    content = paths.templates() / "content"
    skill = target / SKILL_DIR
    installed = load_manifest(skill)
    placed = [(content / name, skill / name) for name in CONTENT_FILES] + [(content / BLANK, target / BLANK)]
    backups = [replace_file(src, dst, installed) for src, dst in placed]
    backups.append(retire_legacy(skill, installed))
    written += [dst for _, dst in placed]
    (skill / MANIFEST).write_text(
        json.dumps({dst.name: digest(src) for src, dst in placed}, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8")

    if sys.platform == "win32":
        subprocess.run(["attrib", "+h", str(target / ".claude")], capture_output=True)
    return {"workspace": str(target), "minutes": minutes, "files": [str(p) for p in written],
            "backups": [str(p) for p in backups if p]}
