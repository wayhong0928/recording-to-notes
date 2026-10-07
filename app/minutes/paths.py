"""程式、模型、工作區的位置（計畫第 5 節）。

程式資料夾用英文名稱，因為 CTranslate2 在 Windows 讀含中文的路徑可能出錯（未實測）。
開發和測試時可以用環境變數換位置：MINUTES_HOME 換程式資料夾，MINUTES_WORKSPACE 換工作區。
"""
import os
import sys
from pathlib import Path

INBOX = "錄音放這裡"
MEETINGS = "會議"
TEMP = "_暫存"


def app_home() -> Path:
    if env := os.environ.get("MINUTES_HOME"):
        return Path(env)
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Application Support" / "MeetingMinutes"
    base = os.environ.get("LOCALAPPDATA") or str(Path.home() / "AppData" / "Local")
    return Path(base) / "MeetingMinutes"


def models_dir() -> Path:
    return app_home() / "models"


def app_root() -> Path:
    """repo 的 app/，安裝後是程式資料夾的 app/。公版、工作區範本都放這裡，跟 minutes 套件同一層。"""
    return Path(__file__).resolve().parent.parent


def templates() -> Path:
    return app_root() / "templates"


def workspace() -> Path:
    if env := os.environ.get("MINUTES_WORKSPACE"):
        return Path(env)
    return Path.home() / "會議紀錄"


def inbox() -> Path:
    return workspace() / INBOX


def meetings() -> Path:
    return workspace() / MEETINGS
