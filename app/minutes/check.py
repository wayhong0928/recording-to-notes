"""檢查環境，只檢查不安裝（計畫第 6、8 節）。轉錄自動選裝置也用這裡的判斷。

三種範圍：
- quick：skill 每次開始都跑，只看轉錄會用到的（套件、裝置、預設模型、工作區），不連網路。
- 預設：quick 再加硬碟空間、網路、Word、Claude Code。
- before_install：安裝前跑，還沒裝的東西列成「資訊」，不算問題；另外列顯示卡驅動夠不夠新、已經裝過哪些東西。
"""
import importlib.util
import os
import platform
import re
import shutil
import subprocess
import sys
import sysconfig
import urllib.request
from dataclasses import asdict, dataclass
from pathlib import Path

from minutes import models, paths

OK, WARN, ERROR, INFO = "ok", "warn", "error", "info"
LABEL = {OK: "正常", WARN: "注意", ERROR: "問題", INFO: "資訊"}


@dataclass
class Item:
    key: str
    label: str
    status: str
    detail: str
    fix: str = ""


def nvidia_info() -> dict | None:
    """有 NVIDIA 顯卡就回傳名稱、驅動版本、運算能力、驅動支援的 CUDA 版本；沒有或查不到回傳 None。"""
    try:
        out = subprocess.run(
            ["nvidia-smi", "--query-gpu=name,driver_version,compute_cap", "--format=csv,noheader"],
            capture_output=True, encoding="utf-8", timeout=15, check=True).stdout
        head = subprocess.run(["nvidia-smi"], capture_output=True, encoding="utf-8", timeout=15).stdout
    except (OSError, subprocess.SubprocessError):
        return None
    first = out.strip().splitlines()[0] if out.strip() else ""
    parts = [p.strip() for p in first.split(",")]
    if len(parts) < 3:
        return None
    return {"name": parts[0], "driver": parts[1], "compute_cap": parts[2], "cuda": driver_cuda(head)}


def driver_cuda(nvidia_smi_head: str) -> str:
    # 舊驅動寫「CUDA Version: 12.8」，新驅動寫「CUDA UMD Version: 13.4」；都找不到回傳空字串
    m = re.search(r"CUDA (?:UMD )?Version:\s*([\d.]+)", nvidia_smi_head)
    return m.group(1) if m else ""


def _ver(s: str) -> tuple[int, ...]:
    return tuple(int(x) for x in re.findall(r"\d+", s)[:2]) or (0,)


def cuda_needed(gpu: dict) -> str:
    # RTX 50 系列（運算能力 12.0）要支援 CUDA 12.8 的驅動；其他卡 CTranslate2 4.x 要 CUDA 12
    return "12.8" if _ver(gpu["compute_cap"]) >= (12, 0) else "12.0"


def gpu_lib_dirs() -> list[Path]:
    """pip 裝的 cuBLAS、cuDNN 的 DLL 資料夾（只有 Windows 用得到）。"""
    return sorted((Path(sysconfig.get_paths()["purelib"]) / "nvidia").glob("*/bin"))


def gpu_libs_installed() -> bool:
    names = {p.name.lower() for d in gpu_lib_dirs() for p in d.glob("*.dll")}
    return any(n.startswith("cublas64_12") for n in names) and any(n.startswith("cudnn64_9") for n in names)


def add_gpu_dlls() -> None:
    # CTranslate2 推論時才用 LoadLibrary 載入 cuBLAS，只認 PATH，add_dll_directory 不夠
    for d in gpu_lib_dirs():
        os.add_dll_directory(str(d))
        os.environ["PATH"] = f"{d}{os.pathsep}{os.environ['PATH']}"


def gpu_status() -> tuple[bool, str, str]:
    """回傳（能不能用 GPU、說明、怎麼修）。不能用時，說明只寫原因，「用 CPU」由呼叫的地方加。"""
    if sys.platform != "win32":
        return False, "v0.1.0 只有 Windows 用顯卡加速", ""
    gpu = nvidia_info()
    if gpu is None:
        return False, "沒有 NVIDIA 顯卡", ""
    need = cuda_needed(gpu)
    # 查不到驅動支援的 CUDA 版本時不擋，交給下面的實際載入和轉錄失敗改 CPU
    if gpu["cuda"] and _ver(gpu["cuda"]) < _ver(need):
        return (False, f"{gpu['name']} 的驅動 {gpu['driver']} 太舊（支援 CUDA {gpu['cuda']}，要 {need} 以上）",
                "到 NVIDIA 官網或電腦廠商的網站更新顯示卡驅動，更新完再跑一次檢查。")
    if not gpu_libs_installed():
        return False, f"有 {gpu['name']}，但 GPU 套件沒裝", "重跑安裝檔，會補裝 GPU 套件。"
    import ctranslate2

    if ctranslate2.get_cuda_device_count() < 1:
        return False, f"有 {gpu['name']}，但轉錄程式抓不到顯卡", "重新開機後再跑一次檢查；還是不行就照常用 CPU。"
    return True, f"用顯卡 {gpu['name']}（驅動 {gpu['driver']}）", ""


def pick_device(requested: str = "auto") -> tuple[str, str]:
    """回傳（cuda 或 cpu、為什麼）。指定 cuda 但不能用時照樣回傳 cuda，讓轉錄時報錯再改 CPU。"""
    if requested == "cpu":
        return "cpu", "指定用 CPU"
    usable, why, _ = gpu_status()
    if usable:
        return "cuda", why
    if requested == "cuda":
        return "cuda", f"指定用顯卡（檢查時發現{why}，顯卡載入或轉錄失敗時會自動改用 CPU）"
    return "cpu", f"用 CPU（{why}）"


def _packages() -> Item:
    missing = [m for m in ("faster_whisper", "ctranslate2", "av", "opencc") if importlib.util.find_spec(m) is None]
    if missing:
        return Item("packages", "轉錄套件", ERROR, f"缺少 {'、'.join(missing)}", "重跑安裝檔。")
    return Item("packages", "轉錄套件", OK, f"Python {platform.python_version()}，套件都在")


def _device() -> Item:
    usable, why, fix = gpu_status()
    return Item("device", "轉錄裝置", OK if usable or not fix else WARN, why if usable else f"用 CPU（{why}）", fix)


def _model(before_install: bool) -> Item:
    m = models.MODELS[models.DEFAULT]
    if models.is_downloaded(m.name):
        return Item("model", "預設模型", OK, f"{m.name} 已下載（{models.path(m.name)}）")
    status = INFO if before_install else WARN
    return Item("model", "預設模型", status, f"{m.name} 還沒下載（約 {m.size_gb} GB）",
                "" if before_install else "第一次轉錄會自動下載，要有網路；或重跑安裝檔先下載。")


def _workspace(before_install: bool) -> Item:
    ws = paths.workspace()
    missing = [p.name for p in (paths.inbox(), paths.meetings()) if not p.is_dir()]
    if not missing:
        return Item("workspace", "工作區", OK, str(ws))
    if before_install:
        return Item("workspace", "工作區", INFO, f"還沒建立（會建在 {ws}）")
    return Item("workspace", "工作區", ERROR, f"{ws} 裡缺少 {'、'.join(missing)}", "重跑安裝檔，會補建工作區。")


def _disk() -> Item:
    target = paths.app_home()
    while not target.exists() and target.parent != target:
        target = target.parent
    free = shutil.disk_usage(target).free / 1024**3
    need = 0 if models.is_downloaded(models.DEFAULT) else models.MODELS[models.DEFAULT].size_gb
    need += 1  # 程式、套件和暫存
    if free < need:
        return Item("disk", "硬碟空間", ERROR, f"剩 {free:.1f} GB，至少要 {need:.1f} GB", "清出硬碟空間再試。")
    return Item("disk", "硬碟空間", OK, f"剩 {free:.1f} GB")


def _network() -> Item:
    try:
        urllib.request.urlopen(urllib.request.Request("https://huggingface.co", method="HEAD"), timeout=8)
    except OSError as e:
        return Item("network", "下載模型的網站", WARN, f"連不上 huggingface.co（{e.__class__.__name__}）",
                    "模型已下載的話不影響轉錄；還沒下載的話，換個網路再試（公司網路可能擋）。")
    return Item("network", "下載模型的網站", OK, "連得上 huggingface.co")


def word_installed() -> bool:
    if sys.platform == "darwin":
        return Path("/Applications/Microsoft Word.app").exists()
    try:
        import winreg

        for root in (winreg.HKEY_LOCAL_MACHINE, winreg.HKEY_CURRENT_USER):
            try:
                winreg.CloseKey(winreg.OpenKey(root, r"SOFTWARE\Microsoft\Windows\CurrentVersion\App Paths\WINWORD.EXE"))
                return True
            except OSError:
                continue
    except ImportError:
        pass
    return False


def claude_cli() -> str | None:
    """終端機版 Claude Code 的位置，沒裝回傳 None。官方安裝程式放在 ~/.local/bin。"""
    found = shutil.which("claude")
    if found:
        return found
    exe = Path.home() / ".local" / "bin" / ("claude.exe" if sys.platform == "win32" else "claude")
    return str(exe) if exe.is_file() else None


def claude_desktop() -> bool:
    if sys.platform == "darwin":
        return Path("/Applications/Claude.app").exists()
    local = Path(os.environ.get("LOCALAPPDATA", ""))
    # Microsoft Store 版裝在 Packages\Claude_*，舊的安裝檔版在 AnthropicClaude
    return any(local.glob("Packages/Claude_*")) or (local / "AnthropicClaude").exists()


def _apps() -> list[Item]:
    items = []
    if word_installed():
        items.append(Item("word", "Word", OK, "有裝"))
    else:
        items.append(Item("word", "Word", WARN, "找不到 Word", "沒有 Word 也能產生 docx，只是不會自動打開。"))
    cli, desktop = claude_cli(), claude_desktop()
    if cli or desktop:
        found = "、".join(n for n, ok in (("終端機版", cli), ("桌面版", desktop)) if ok)
        items.append(Item("claude", "Claude Code", OK, f"有裝（{found}）"))
    else:
        items.append(Item("claude", "Claude Code", WARN, "找不到 Claude Code",
                          "照 code.claude.com/docs 的說明安裝 Claude Code，用付費方案的帳號登入。"))
    return items


def installed() -> Item:
    """安裝前列出已經裝過的東西，重跑安裝時會跳過或更新。"""
    home = paths.app_home()
    found = [name for name, ok in (
        ("程式", (home / "app" / "minutes").is_dir()),
        ("Python 環境", (home / ".venv").is_dir()),
        *((f"模型 {n}", models.is_downloaded(n)) for n in models.MODELS),
        ("工作區", paths.inbox().is_dir()),
    ) if ok]
    return Item("installed", "已經裝過的", INFO, "、".join(found) if found else "沒有，這是第一次安裝")


def gpu_before_install() -> Item:
    gpu = nvidia_info() if sys.platform == "win32" else None
    if gpu is None:
        why = "Mac 一律用 CPU" if sys.platform == "darwin" else "沒有 NVIDIA 顯卡，會用 CPU"
        return Item("gpu", "顯示卡", INFO, why)
    need = cuda_needed(gpu)
    name = f"{gpu['name']}，驅動 {gpu['driver']}"
    if gpu["cuda"] and _ver(gpu["cuda"]) < _ver(need):
        return Item("gpu", "顯示卡", WARN, f"{name}，太舊（支援 CUDA {gpu['cuda']}，要 {need} 以上），這次先用 CPU 裝",
                    "到 NVIDIA 官網或電腦廠商的網站更新顯示卡驅動，更新完重跑安裝檔就會改用顯卡。")
    return Item("gpu", "顯示卡", OK, f"{name}，會裝顯卡加速套件")


def run(quick: bool = False, before_install: bool = False) -> list[Item]:
    items = [Item("system", "作業系統", INFO, f"{platform.system()} {platform.release()}（{platform.machine()}）")]
    if before_install:
        items += [gpu_before_install(), installed()]
    else:
        items += [_packages(), _device()]
    items += [_model(before_install), _workspace(before_install)]
    if not quick:
        items += [_disk(), _network(), *_apps()]
    return items


def report(items: list[Item]) -> str:
    lines = []
    for it in items:
        lines.append(f"[{LABEL[it.status]}] {it.label}：{it.detail}")
        if it.fix:
            lines.append(f"       怎麼修：{it.fix}")
    return "\n".join(lines)


def as_json(items: list[Item]) -> dict:
    bad = [i.label for i in items if i.status == ERROR]
    data = {"ok": not bad, "items": [asdict(i) for i in items]}
    if bad:
        data["error"] = f"檢查有問題：{'、'.join(bad)}"
    return data
