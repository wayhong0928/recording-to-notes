"""進度視窗冒煙測試：真的開一次視窗，3 秒後把進度改成完成，看視窗有沒有自己關掉。

CI 在 Windows 和 Mac 上跑，用來知道這個平台開不開得了 tkinter 視窗。
開不起來時 show_window 會馬上安靜結束（轉錄照跑），這裡就印「沒開起來」並回傳 1。
"""
import os
import sys
import tempfile
import threading
import time
from pathlib import Path

os.environ.setdefault("MINUTES_PROGRESS_DIR", tempfile.mkdtemp())
sys.stdout.reconfigure(encoding="utf-8")  # 英文語系 Windows 預設編不了中文

from minutes import progress  # noqa: E402

folder = Path(tempfile.mkdtemp()) / "2026-01-01_視窗測試"
folder.mkdir()
tracker = progress.Tracker(folder, 100.0, 1)
tracker.update(30.0)
threading.Timer(3, tracker.finish).start()

try:
    import tkinter

    print(f"tkinter 可以載入（Tk {tkinter.TkVersion}）")
except ImportError as e:
    print(f"tkinter 載入失敗：{e}")
    sys.exit(1)

t0 = time.monotonic()
progress.show_window(folder)
spent = time.monotonic() - t0
if spent < 2:
    print(f"視窗沒開起來（{spent:.1f} 秒就結束）")
    sys.exit(1)
print(f"視窗開了 {spent:.1f} 秒，進度改成完成後自己關掉")
