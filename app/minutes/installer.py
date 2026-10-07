"""安裝（計畫第 8 節）。安裝檔確認有 uv 之後，用 uv 的 Python 跑這裡，所以這個檔只能用標準函式庫。

流程：安裝前檢查 → 列出要裝什麼、按 Enter 才開始 → 依序做下面幾步。
每一步都可以重跑：模型已下載就跳過，其他步驟照新版重做，不會動到工作區裡的錄音和會議紀錄。
1. 把 app\\ 複製到程式資料夾（更新時只換這部分，模型和工作區不動）
2. uv 依 uv.lock 裝 Python 3.12 和套件到程式資料夾的 .venv
3. 有 NVIDIA 顯卡、驅動夠新就加裝 GPU 套件（只有 Windows）
4. 下載預設模型
5. 建工作區，放 skill、使用說明和術語表範例
6. 桌面建打開工作區的捷徑
7. 用系統內建的語音合成一段錄音，試跑轉錄和產生 Word
"""
import os
import shutil
import subprocess
import sys
import tempfile
from datetime import datetime
from pathlib import Path

from minutes import check, models, paths

# 不複製到程式資料夾的東西：開發環境、快取、評測的輸出
SKIP = shutil.ignore_patterns(".venv", "__pycache__", ".pytest_cache", "out", "*.pyc")
TRIAL_TEXT_ZH = "這是會議紀錄小幫手的安裝測試，下週三下午兩點開會。"
TRIAL_TEXT_EN = "This is a test of the meeting minutes installer."


class InstallError(Exception):
    pass


class Log:
    """印到畫面，同時寫進 logs/install.log。"""

    def __init__(self, home: Path):
        (home / "logs").mkdir(parents=True, exist_ok=True)
        self.file = (home / "logs" / "install.log").open("a", encoding="utf-8")
        self.file.write(f"\n===== {datetime.now():%Y-%m-%d %H:%M:%S} 開始安裝 =====\n")

    def __call__(self, msg: str = "") -> None:
        print(msg, flush=True)
        self.file.write(msg + "\n")
        self.file.flush()

    def close(self) -> None:
        self.file.close()


def venv_dir(home: Path) -> Path:
    return home / ".venv"


def venv_python(home: Path) -> Path:
    return venv_dir(home) / ("Scripts/python.exe" if sys.platform == "win32" else "bin/python")


def venv_minutes(home: Path) -> Path:
    return venv_dir(home) / ("Scripts/minutes.exe" if sys.platform == "win32" else "bin/minutes")


def uv_exe() -> str:
    found = shutil.which("uv")
    if found:
        return found
    exe = Path.home() / ".local" / "bin" / ("uv.exe" if sys.platform == "win32" else "uv")
    if exe.is_file():
        return str(exe)
    raise InstallError("找不到 uv。請用安裝檔（安裝（Windows）.bat 或 安裝（Mac）.command）安裝，它會先裝好 uv。")


def run(cmd: list, log: Log, env: dict | None = None) -> str:
    """跑外部指令，輸出寫進 log；失敗時把最後幾行放進錯誤訊息。
    Windows 的 Python 輸出被接管時預設用 cp950，設 PYTHONUTF8 統一成 UTF-8。"""
    log.file.write("$ " + " ".join(str(c) for c in cmd) + "\n")
    p = subprocess.run([str(c) for c in cmd], capture_output=True, encoding="utf-8", errors="replace",
                       env={**os.environ, "PYTHONUTF8": "1", **(env or {})})
    log.file.write(p.stdout + p.stderr)
    log.file.flush()
    if p.returncode != 0:
        tail = "\n".join((p.stdout + p.stderr).strip().splitlines()[-8:])
        raise InstallError(f"指令失敗（結束代碼 {p.returncode}）：\n{tail}")
    return p.stdout


def want_gpu() -> bool:
    return check.gpu_before_install().status == check.OK and sys.platform == "win32"


def plan_text(gpu: bool, shortcut: bool = True, trial: bool = True) -> str:
    home, ws = paths.app_home(), paths.workspace()
    m = models.MODELS[models.DEFAULT]
    todo = [f"把程式放到 {home}",
            "安裝 Python 3.12 和轉錄套件（約 1 GB，裝在程式資料夾，不動你電腦原本的 Python）"]
    if gpu:
        todo.append("安裝顯示卡加速套件（約 1.5 GB）")
    if not models.is_downloaded(m.name):
        todo.append(f"下載語音辨識模型 {m.name}（約 {m.size_gb} GB）")
    todo.append(f"建立工作區 {ws}（錄音放這裡、會議、使用說明）")
    if shortcut:
        todo.append("在桌面建一個打開工作區的捷徑")
    if trial:
        todo.append("用一小段合成語音試跑一次")
    return "\n".join(["接下來會做這些事："] + [f"  {n}. {t}" for n, t in enumerate(todo, 1)])


def copy_app(home: Path, log: Log) -> None:
    src, dst = paths.app_root(), home / "app"
    if src.resolve() == dst.resolve():
        log("  程式已經在程式資料夾，跳過複製。")
        return
    if dst.exists():
        shutil.rmtree(dst)
    shutil.copytree(src, dst, ignore=SKIP)
    log(f"  已複製到 {dst}")


def sync_env(home: Path, gpu: bool, log: Log) -> None:
    cmd = [uv_exe(), "sync", "--frozen", "--no-dev", "--python", "3.12", "--project", home / "app"]
    if gpu:
        cmd += ["--extra", "gpu"]
    # 環境放程式資料夾的 .venv，不放 app\ 裡，更新程式時不用重裝套件
    run(cmd, log, env={"UV_PROJECT_ENVIRONMENT": str(venv_dir(home))})
    log(f"  Python 環境：{venv_dir(home)}")


def in_venv(home: Path, code: str, log: Log) -> str:
    return run([venv_python(home), "-c", code], log)


def download_model(home: Path, log: Log) -> None:
    name = models.DEFAULT
    if models.is_downloaded(name):
        log(f"  {name} 已經下載過，跳過。")
        return
    log(f"  下載中，約 {models.MODELS[name].size_gb} GB，視網路速度要幾分鐘到半小時。中斷了重跑安裝檔會接著下載。")
    in_venv(home, f"from minutes import models; models.ensure({name!r}, log=lambda m: None)", log)
    log(f"  已下載到 {models.path(name)}")


def setup_workspace(home: Path, log: Log) -> None:
    code = ("import json; from minutes import workspace; "
            f"print(json.dumps(workspace.setup(minutes={venv_minutes(home).as_posix()!r})))")
    in_venv(home, code, log)
    ws = paths.workspace()
    for name in ("使用說明.html", "術語表範例.txt"):
        src = home / "app" / "docs" / name
        if src.is_file():
            shutil.copy2(src, ws / name)
    log(f"  工作區：{ws}")


def desktop_dir() -> Path:
    if sys.platform == "win32":
        # OneDrive 會把桌面搬走，用系統回報的位置
        out = subprocess.run(["powershell", "-NoProfile", "-Command", "[Environment]::GetFolderPath('Desktop')"],
                             capture_output=True, encoding="utf-8", errors="replace")
        if out.stdout.strip():
            return Path(out.stdout.strip())
    return Path.home() / "Desktop"


def ansi_ok(*items: Path) -> bool:
    """WScript.Shell 的捷徑只認系統語系的字碼頁（繁中 Windows 是 cp950），編不了的路徑會靜靜存檔失敗。"""
    if sys.platform != "win32":
        return True
    import ctypes

    try:
        for p in items:
            str(p).encode(f"cp{ctypes.windll.kernel32.GetACP()}")
    except (UnicodeEncodeError, LookupError):
        return False
    return True


def make_shortcut(log: Log, desktop: Path | None = None) -> None:
    ws = paths.workspace()
    desktop = desktop or desktop_dir()
    if sys.platform == "win32":
        lnk = desktop / "會議紀錄.lnk"
        if not ansi_ok(lnk, ws):
            log(f"  桌面捷徑：這台 Windows 的系統語系不支援路徑裡的文字（例如英文語系的 Windows），捷徑建不了，直接打開 {ws} 就好。")
            return
        lnk.unlink(missing_ok=True)  # 先刪舊的，才分得出這次有沒有建成功
        q = lambda p: str(p).replace("'", "''")  # PowerShell 單引號字串裡的 ' 要寫兩次
        ps = (f"$s=(New-Object -ComObject WScript.Shell).CreateShortcut('{q(lnk)}');"
              f"$s.TargetPath='{q(ws)}';$s.Save()")
        subprocess.run(["powershell", "-NoProfile", "-Command", ps], capture_output=True)
        made = lnk.exists()
    else:
        link = desktop / "會議紀錄"
        if not link.exists():
            link.symlink_to(ws)
        made = link.exists()
    log(f"  桌面捷徑：{'已建立' if made else '沒建成功，直接打開 ' + str(ws) + ' 也可以'}")


def synth_speech(wav: Path, log: Log) -> bool:
    """用系統內建的語音合成產生測試錄音。回傳是不是中文語音。"""
    if sys.platform == "win32":
        ps = ("Add-Type -AssemblyName System.Speech;"
              "$s=New-Object System.Speech.Synthesis.SpeechSynthesizer;"
              "$v=$s.GetInstalledVoices()|?{$_.VoiceInfo.Culture.Name -like 'zh-*'}|select -First 1;"
              "if($v){$s.SelectVoice($v.VoiceInfo.Name);$t=$env:TRIAL_ZH;$z='zh'}else{$t=$env:TRIAL_EN;$z='en'};"
              f"$s.SetOutputToWaveFile('{str(wav).replace(chr(39), chr(39) * 2)}');$s.Speak($t);$s.Dispose();Write-Output $z")
        out = subprocess.run(["powershell", "-NoProfile", "-Command", ps], capture_output=True, encoding="utf-8",
                             errors="replace", env={**os.environ, "TRIAL_ZH": TRIAL_TEXT_ZH, "TRIAL_EN": TRIAL_TEXT_EN})
        zh = out.stdout.strip().endswith("zh")
    else:
        voices = subprocess.run(["say", "-v", "?"], capture_output=True, encoding="utf-8").stdout
        zh = "zh_TW" in voices or "zh_CN" in voices
        aiff = wav.with_suffix(".aiff")
        subprocess.run(["say", "-o", str(aiff), TRIAL_TEXT_ZH if zh else TRIAL_TEXT_EN], capture_output=True)
        subprocess.run(["afconvert", "-f", "WAVE", "-d", "LEI16@16000", str(aiff), str(wav)], capture_output=True)
    if not wav.is_file() or wav.stat().st_size < 1000:
        raise InstallError("系統的語音合成沒有產生錄音，試跑做不了。")
    return zh


def trial_run(home: Path, log: Log) -> dict:
    """試跑轉錄和產生 Word，不動使用者的工作區。顯卡失敗時 transcribe 會自己改用 CPU。"""
    import json

    with tempfile.TemporaryDirectory() as tmp:
        folder = Path(tmp) / "2026-01-01_安裝測試"
        folder.mkdir()
        zh = synth_speech(folder / "測試 20260101_090000.wav", log)
        exe = venv_minutes(home)
        out = run([exe, "transcribe", folder, "--no-window", "--json"], log)
        result = json.loads(out.strip().splitlines()[-1])
        if not result.get("ok", True):
            raise InstallError(f"試跑轉錄失敗：{result.get('error')}")
        text = (folder / "1_逐字稿.md").read_text(encoding="utf-8")
        (folder / "2_會議紀錄.md").write_text(
            (paths.templates() / "content" / "問答式.md").read_text(encoding="utf-8"), encoding="utf-8")
        run([exe, "render", folder, "--no-open", "--json"], log)
        if not list(folder.glob("2_會議紀錄_*.docx")):
            raise InstallError("試跑產生 Word 失敗。")
    lines = [ln[2:] for ln in text.splitlines() if ln.startswith("- [")]
    log(f"  語音：{'中文' if zh else '英文（這台沒有中文語音，只確認流程跑得通）'}")
    log(f"  轉出來的文字：{lines[0] if lines else '（沒有文字）'}")
    if result.get("fallback"):
        log(f"  注意：{result['fallback']}")
    return result


STEPS = [
    ("複製程式", lambda home, gpu, log: copy_app(home, log)),
    ("安裝 Python 和套件", lambda home, gpu, log: sync_env(home, gpu, log)),
    ("下載語音辨識模型", lambda home, gpu, log: download_model(home, log)),
    ("建立工作區", lambda home, gpu, log: setup_workspace(home, log)),
    ("桌面捷徑", lambda home, gpu, log: make_shortcut(log)),
    ("試跑一次", lambda home, gpu, log: trial_run(home, log)),
]


def install(yes: bool = False, shortcut: bool = True, trial: bool = True) -> int:
    home = paths.app_home()
    items = check.run(before_install=True)
    print("安裝前檢查：")
    print(check.report(items))
    bad = [i for i in items if i.status == check.ERROR]
    if bad:
        print("\n上面有「問題」的項目要先處理，處理完再雙擊安裝檔。")
        return 1
    gpu = want_gpu()
    print("\n" + plan_text(gpu, shortcut, trial))
    if not yes:
        try:
            input("\n按 Enter 開始安裝，或直接關掉視窗取消。")
        except EOFError:
            pass

    log = Log(home)
    steps = [s for s in STEPS if (shortcut or s[0] != "桌面捷徑") and (trial or s[0] != "試跑一次")]
    try:
        for n, (name, fn) in enumerate(steps, 1):
            log(f"\n[{n}/{len(steps)}] {name}")
            fn(home, gpu, log)
    except Exception as e:  # 不認得的錯誤也要告訴使用者是哪一步、記錄在哪
        detail = str(e) if isinstance(e, (InstallError, OSError)) else f"{e.__class__.__name__}：{e}"
        log(f"\n安裝在「{name}」這一步失敗：{detail}")
        log(f"詳細記錄在 {home / 'logs' / 'install.log'}。修好後再雙擊安裝檔，已下載的模型不會重新下載。")
        log.close()
        return 1
    log("\n安裝完成。")
    log(f"每次開會的錄音放進「{paths.inbox()}」，")
    log(f"在 Claude Code 打開「{paths.workspace()}」這個資料夾，輸入 /會議紀錄。")
    log.close()
    return 0
