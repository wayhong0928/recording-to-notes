"""轉錄進度：transcribe 寫進度檔，進度視窗和 minutes progress 讀它。

進度檔放系統暫存資料夾，不放會議資料夾：會議資料夾可能在 OneDrive、iCloud 裡，
每幾秒改一次檔會一直觸發同步和防毒掃描。測試可以用環境變數 MINUTES_PROGRESS_DIR 換位置。
視窗是另外一個程序，關掉視窗或開不起來都不影響轉錄。
"""
import hashlib
import json
import os
import subprocess
import sys
import tempfile
import threading
import time
from pathlib import Path

WRITE_EVERY = 5  # 秒，轉錄中最多這麼久寫一次
HEARTBEAT = 5  # 秒，沒有新進度也更新 updated，視窗才分得出程式還在不在
STALE_AFTER = 30  # 秒，updated 超過這麼久沒變就當作停了
ETA_AFTER = 60  # 秒，轉錄開始滿這麼久
ETA_MIN_SHARE = 0.05  # 而且轉超過這個比例，才給預估剩餘時間
WAIT_FOR_FILE = 30  # 秒，視窗等進度檔出現的上限
RUNNING = ("loading", "transcribing")


def progress_dir() -> Path:
    if env := os.environ.get("MINUTES_PROGRESS_DIR"):
        return Path(env)
    return Path(tempfile.gettempdir()) / "MeetingMinutes" / "progress"


def progress_file(folder: Path) -> Path:
    key = os.path.normcase(str(Path(folder).resolve()))
    return progress_dir() / f"{hashlib.sha1(key.encode('utf-8')).hexdigest()[:16]}.json"


def read(folder: Path) -> dict | None:
    try:
        return json.loads(progress_file(folder).read_text(encoding="utf-8"))
    except (OSError, ValueError):  # 沒有檔案，或剛好在換檔
        return None


def clean_old(days: int = 7) -> None:
    """刪掉很久以前的進度檔和沒換名成功的暫存檔，免得暫存資料夾越堆越多。"""
    cutoff = time.time() - days * 86400
    try:
        for f in progress_dir().iterdir():
            if f.stat().st_mtime < cutoff:
                f.unlink()
    except OSError:
        pass


class Tracker:
    """transcribe 用：記錄進度並寫進度檔。寫不進去只略過，不讓轉錄失敗。"""

    def __init__(self, folder: Path, total: float, parts: int):
        self.path = progress_file(folder)
        self.data = {"state": "loading", "folder": Path(folder).name, "total": total, "done": 0.0,
                     "part": 0, "parts": parts, "started": time.time(), "updated": 0.0,
                     "speed_from": None, "done_at": None, "error": ""}
        self._lock = threading.Lock()
        self._last_write = 0.0
        self._stop = threading.Event()
        clean_old()
        self._write()
        threading.Thread(target=self._beat, daemon=True).start()

    def _beat(self) -> None:
        while not self._stop.wait(HEARTBEAT):
            self._write()

    def _write(self) -> None:
        with self._lock:
            self.data["updated"] = time.time()
            self._last_write = time.monotonic()
            try:
                self.path.parent.mkdir(parents=True, exist_ok=True)
                tmp = self.path.with_suffix(f".{os.getpid()}.tmp")
                tmp.write_text(json.dumps(self.data, ensure_ascii=False), encoding="utf-8")
                tmp.replace(self.path)
            except OSError:  # Windows 上視窗剛好在讀時換名會失敗，下一次再寫
                pass

    def start_part(self, part: int, done: float) -> None:
        self.data.update(part=part, done=done)
        self._write()

    def update(self, done: float) -> None:
        now = time.time()
        if self.data["state"] != "transcribing":
            # 第一次有進度才算開始轉，載入模型的時間不算進速度
            self.data.update(state="transcribing", speed_from=[now, done])
        self.data.update(done=done, done_at=now)
        if time.monotonic() - self._last_write >= WRITE_EVERY:
            self._write()

    def finish(self) -> None:
        self._stop.set()
        self.data.update(state="done", done=self.data["total"])
        self._write()

    def fail(self, message: str) -> None:
        self._stop.set()
        self.data.update(state="error", error=message)
        self._write()


def summarize(data: dict | None, now: float | None = None) -> dict:
    """進度檔加上百分比、預估剩餘秒數、有沒有停住。"""
    if not data:
        return {"state": "none"}
    now = time.time() if now is None else now
    total, done = data["total"], min(data["done"], data["total"])
    eta = None
    if data["state"] == "transcribing" and data.get("speed_from") and data.get("done_at"):
        t0, done0 = data["speed_from"]
        spent = data["done_at"] - t0
        if spent >= ETA_AFTER and total and done / total >= ETA_MIN_SHARE and done > done0:
            speed = (done - done0) / spent
            eta = max(0, round((total - done) / speed - (now - data["done_at"])))
    return {
        "state": data["state"], "folder": data["folder"],
        "percent": int(done / total * 100) if total else 0,
        "part": data["part"], "parts": data["parts"],
        "elapsed": max(0, round(now - data["started"])), "eta": eta,
        "stale": data["state"] in RUNNING and now - data["updated"] > STALE_AFTER,
        "error": data.get("error", ""),
    }


def fmt_minutes(sec: float) -> str:
    m = round(sec / 60)
    if m < 1:
        return "不到 1 分鐘"
    h, m = divmod(m, 60)
    return f"{h} 小時 {m} 分鐘" if h and m else f"{h} 小時" if h else f"{m} 分鐘"


def text(s: dict) -> str:
    """給 minutes progress 和視窗用的一行說明。"""
    if s["state"] == "none":
        return "還沒有轉錄進度（沒在轉，或剛開始）。"
    if s["state"] == "done":
        return "轉錄完成。"
    if s["state"] == "error":
        return f"轉錄失敗：{s['error']}"
    if s["stale"]:
        return "轉錄好像停了：超過 30 秒沒有新的進度。"
    if s["state"] == "loading":
        return f"準備模型中（第一次用會先下載），已經過了 {fmt_minutes(s['elapsed'])}。"
    eta = f"，大概還要 {fmt_minutes(s['eta'])}" if s["eta"] is not None else "，正在估算還要多久"
    return f"第 {s['part']}／{s['parts']} 段，已轉 {s['percent']}%{eta}。"


def window_disabled() -> bool:
    return bool(os.environ.get("MINUTES_NO_WINDOW"))


def launch_window(folder: Path) -> bool:
    """另開一個程序顯示進度視窗。開不起來就算了，回傳有沒有啟動。"""
    if window_disabled():
        return False
    exe = Path(sys.executable)
    kw: dict = {"stdin": subprocess.DEVNULL, "stdout": subprocess.DEVNULL, "stderr": subprocess.DEVNULL}
    if sys.platform == "win32":
        if (w := exe.with_name("pythonw.exe")).is_file():  # 不會多跳一個黑色主控台
            exe = w
        kw["creationflags"] = subprocess.CREATE_NEW_PROCESS_GROUP | subprocess.CREATE_NO_WINDOW
    else:
        kw["start_new_session"] = True
    try:
        subprocess.Popen([str(exe), "-m", "minutes", "progress", str(folder), "--show-window"], **kw)
    except OSError:
        return False
    return True


def show_window(folder: Path) -> int:
    """進度視窗。轉完就關；失敗或停住時留著，等使用者自己關。"""
    deadline = time.monotonic() + WAIT_FOR_FILE
    while (data := read(folder)) is None:
        if time.monotonic() > deadline:
            return 0
        time.sleep(0.5)
    if data["state"] == "done":
        return 0
    try:
        import tkinter as tk
        from tkinter import font as tkfont
        from tkinter import ttk

        root = tk.Tk()
    except Exception:  # 沒有桌面環境或 Tk 壞了
        return 0

    root.title("會議紀錄小幫手：轉錄中")
    root.resizable(False, False)
    if sys.platform == "win32":
        tkfont.nametofont("TkDefaultFont").configure(family="Microsoft JhengHei UI", size=10)
    frame = ttk.Frame(root, padding=16)
    frame.pack(fill="both", expand=True)
    name = ttk.Label(frame, text=data["folder"])
    name.pack(anchor="w")
    bar = ttk.Progressbar(frame, length=360, maximum=100)
    bar.pack(fill="x", pady=(8, 6))
    status = ttk.Label(frame, wraplength=360, justify="left")
    status.pack(anchor="w")
    elapsed = ttk.Label(frame)
    elapsed.pack(anchor="w")
    ttk.Label(frame, text="關掉這個視窗不會停止轉錄。", foreground="gray").pack(anchor="w", pady=(8, 0))
    # 跳到最上層一次，之後不再搶前面
    root.lift()
    root.attributes("-topmost", True)
    root.after(1500, lambda: root.attributes("-topmost", False))
    last = [data]

    def tick() -> None:
        last[0] = read(folder) or last[0]
        s = summarize(last[0])
        if s["state"] == "done":
            root.destroy()
            return
        bar["value"] = s["percent"]
        status["text"] = text(s)
        status["foreground"] = "firebrick" if s["state"] == "error" or s["stale"] else ""
        elapsed["text"] = f"已經跑了 {fmt_minutes(s['elapsed'])}"
        if s["state"] == "error":
            root.title("會議紀錄小幫手：轉錄失敗")
            return  # 不再更新，留著給使用者看
        root.after(1000, tick)

    tick()
    root.mainloop()
    return 0
