"""模型清單、下載、是否已下載（計畫第 9 節）。

模型放程式資料夾的 models/<名稱>/，不用 Hugging Face 預設的快取位置，
這樣移除程式時模型一起刪，也看得出佔了多少空間。
"""
from dataclasses import dataclass
from pathlib import Path

from minutes import paths

DEFAULT = "breeze"
# faster-whisper 自己下載時抓的檔案，照抄
FILES = ["config.json", "preprocessor_config.json", "model.bin", "tokenizer.json", "vocabulary.*"]


@dataclass(frozen=True)
class Model:
    name: str
    repo: str
    size_gb: float  # 10-07 在這台量的下載量
    note: str
    simplified: bool = True  # 輸出簡體字，要轉成正體


MODELS = {
    # 聯發科 Breeze-ASR-25（台灣華語、中英夾雜）的社群 CT2 轉檔版。本來就輸出正體，
    # 再轉一次只會改錯字（10-07 測試集 1152 字裡，轉換改了 3 個字，3 個都改錯：最多只能→最多隻能）
    "breeze": Model("breeze", "phate334/Breeze-ASR-25-ct2", 2.9, "預設，台灣口音和中英夾雜比較準", simplified=False),
    "turbo": Model("turbo", "dropbox-dash/faster-whisper-large-v3-turbo", 1.5, "快速模式"),
    "large-v3": Model("large-v3", "Systran/faster-whisper-large-v3", 2.9, "OpenAI 原版"),
}


def outputs_simplified(name: str) -> bool:
    """不在清單裡的名稱（例如評測用的 large-v3-turbo）當作 Whisper 原版，輸出簡體。"""
    return MODELS[name].simplified if name in MODELS else True


def path(name: str) -> Path:
    return paths.models_dir() / name


def is_downloaded(name: str) -> bool:
    """必要的檔案都在，而且沒有下載到一半的暫存檔（huggingface_hub 放在 .cache 底下的 *.incomplete）。"""
    d = path(name)
    needed = ("model.bin", "config.json", "tokenizer.json")
    if not all((d / f).is_file() for f in needed) or not any(d.glob("vocabulary.*")):
        return False
    return not any((d / ".cache").rglob("*.incomplete"))


def ensure(name: str, log=print) -> Path:
    """沒下載就下載，回傳模型資料夾。huggingface_hub 會接著下載中斷的檔案。"""
    if is_downloaded(name):
        return path(name)
    from huggingface_hub import snapshot_download

    m = MODELS[name]
    log(f"第一次使用 {name}，下載模型（約 {m.size_gb} GB），中斷了重跑會接著下載。")
    snapshot_download(m.repo, local_dir=path(name), allow_patterns=FILES)
    return path(name)
