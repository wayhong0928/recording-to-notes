"""建會議資料夾、把錄音搬進去（計畫第 5、6 節）。

資料夾名稱是「日期_會議名稱」，預設建在工作區的「會議」，給了 --to 就建在那裡。
錄音保留原檔名；同名的資料夾已經存在時加 _2、_3，不覆蓋。
"""
import re
import shutil
from datetime import date
from pathlib import Path

from minutes import paths
from minutes.recordings import AUDIO_EXTS

# 會議資料夾名稱的上限；Windows 路徑太長（超過 260 字元）時很多程式會打不開
MAX_NAME = 50
# Windows 檔名不能用的字元，換成全形或拿掉
_BAD = str.maketrans({"<": "＜", ">": "＞", ":": "：", '"': "＂", "/": "／", "\\": "＼", "|": "｜", "?": "？", "*": "＊"})


class MeetingError(Exception):
    pass


def safe_name(name: str) -> str:
    name = re.sub(r"[\x00-\x1f]", "", name.translate(_BAD)).strip().rstrip(". ")
    if not name:
        raise MeetingError("會議名稱是空的")
    if len(name) > MAX_NAME:
        raise MeetingError(f"會議名稱太長（{len(name)} 個字），請縮短到 {MAX_NAME} 個字以內")
    return name


def resolve_recording(arg: str) -> Path:
    """錄音可以給完整路徑，或只給「錄音放這裡」裡的檔名。只給檔名時先找「錄音放這裡」，再找目前的資料夾。"""
    p = Path(arg)
    candidates = [p] if p.is_absolute() else [paths.inbox() / arg, p]
    found = next((c for c in candidates if c.is_file()), None)
    if found is None:
        raise MeetingError(f"找不到錄音：{arg}")
    if found.suffix.lower() not in AUDIO_EXTS:
        raise MeetingError(f"不是錄音檔：{arg}（支援 {'、'.join(sorted(AUDIO_EXTS))}）")
    return found


def create(name: str, day: str, recordings: list[str], to: str | None = None) -> tuple[Path, list[Path]]:
    """回傳（會議資料夾、搬進去之後的錄音路徑）。先檢查全部錄音都在，才建資料夾、開始搬。"""
    try:
        date.fromisoformat(day)
    except ValueError:
        raise MeetingError(f"日期要寫成 YYYY-MM-DD：{day}") from None
    sources = [resolve_recording(r) for r in recordings]
    names = [s.name for s in sources]
    if dup := {n for n in names if names.count(n) > 1}:
        raise MeetingError(f"錄音檔名重複：{'、'.join(sorted(dup))}")

    base = Path(to).expanduser() if to else paths.meetings()
    folder = base / f"{day}_{safe_name(name)}"
    n = 2
    while folder.exists():
        folder = base / f"{day}_{safe_name(name)}_{n}"
        n += 1
    folder.mkdir(parents=True)
    moved: list[tuple[Path, Path]] = []
    try:
        for s in sources:
            dest = folder / s.name
            shutil.move(str(s), str(dest))
            moved.append((s, dest))
    except OSError as e:
        # 搬到一半失敗：已經搬的搬回原處，刪掉空的會議資料夾，像沒做過一樣。
        # 錄音被別的程式開著時，move 改名失敗會改成複製再刪原檔，刪原檔才失敗，留下一份複本，要刪掉
        if s.exists() and dest.exists():
            dest.unlink()
        for src, done in reversed(moved):
            shutil.move(str(done), str(src))
        if not any(folder.iterdir()):
            folder.rmdir()
        raise MeetingError(f"搬錄音時出錯（{e}），已經把搬過的錄音放回原處") from e
    return folder, [dest for _, dest in moved]
