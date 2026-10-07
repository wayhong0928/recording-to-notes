"""去識別化檢查：repo 裡不能出現客戶名稱、公司名稱、同事名字。

掃描範圍是所有要進版控的檔案（已追蹤，加上還沒追蹤但沒被 ignore 的）：
- 檔案路徑本身
- 文字檔內容
- docx 內文（解壓縮讀 XML，去掉標籤再比對，Word 把一個詞拆成好幾段也抓得到）
- docx 的作者、最後修改者、公司欄位，只能是空的或 AUTHOR_OK 裡的值
- 所有 commit 訊息

禁用字詞清單在 repo 根目錄的 private/禁用字詞.txt（不進版控），一行一個詞，# 開頭是註解。
英文不分大小寫，而且整個字比對（AB 不會撞到 tabs）；中文照字串比對。
清單只給開發者自己看：命中時預設只印「清單第幾個詞」，不印詞本身，也不印 docx 欄位的值，
交給 AI 跑也不會把清單內容帶出去。自己在終端機看時才加 --show。

用法（在 app\\ 底下）：
    uv run python tools\\check_names.py          每次 commit 前跑
    uv run python tools\\check_names.py --ci     GitHub Actions 用：看不到清單，只檢查 docx 欄位
    uv run python tools\\check_names.py --show   命中時印出詞本身和 docx 欄位的值
結束代碼：0 沒有命中、1 有命中、2 清單不存在或讀不到 git 的檔案清單、commit 訊息
"""
import argparse
import html
import re
import subprocess
import sys
import zipfile
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
DEFAULT_LIST = REPO / "private" / "禁用字詞.txt"
AUTHOR_OK = {"", "python-docx", "會議紀錄小幫手"}
# 作者、最後修改者在 core.xml，公司在 app.xml
AUTHOR_FIELDS = {
    "docProps/core.xml": ("dc:creator", "cp:lastModifiedBy"),
    "docProps/app.xml": ("Company", "Manager"),
}


def git(*args: str) -> str:
    return subprocess.run(["git", "-C", str(REPO), *args], capture_output=True, check=True,
                          encoding="utf-8").stdout


def repo_files() -> list[Path]:
    names = git("ls-files", "-z", "--cached", "--others", "--exclude-standard").split("\0")
    return [REPO / n for n in names if n and (REPO / n).is_file()]


def load_terms(path: Path) -> list[str]:
    lines = path.read_text(encoding="utf-8-sig").splitlines()
    return [s for s in (ln.strip() for ln in lines) if s and not s.startswith("#")]


def find_terms(text: str, terms: list[str]) -> list[str]:
    low = text.lower()
    hits = []
    for t in terms:
        if t.isascii():
            # 英文詞要整個字比對，不然短縮寫會撞到一般單字（例如 tabs 裡的 ab）
            if re.search(rf"(?<![a-z0-9]){re.escape(t.lower())}(?![a-z0-9])", low):
                hits.append(t)
        elif t.lower() in low:
            hits.append(t)
    return hits


def read_text(path: Path) -> str | None:
    """讀文字檔；二進位檔回傳 None。不是 UTF-8 的文字檔改用 cp950 讀，並提醒一聲。"""
    data = path.read_bytes()
    if b"\0" in data[:8192]:
        return None
    try:
        return data.decode("utf-8")
    except UnicodeDecodeError:
        print(f"提醒：{path.name} 不是 UTF-8，改用 cp950 讀")
        return data.decode("cp950", "replace")


def docx_text(path: Path) -> str:
    with zipfile.ZipFile(path) as z:
        parts = [z.read(n).decode("utf-8", "replace") for n in z.namelist() if n.endswith((".xml", ".rels"))]
    return html.unescape(re.sub(r"<[^>]+>", "", "\n".join(parts)))


def docx_authors(path: Path) -> list[str]:
    bad = []
    with zipfile.ZipFile(path) as z:
        for part, tags in AUTHOR_FIELDS.items():
            if part not in z.namelist():
                continue
            xml = z.read(part).decode("utf-8", "replace")
            for tag in tags:
                for value in re.findall(rf"<{tag}>([^<]*)</{tag}>", xml):
                    if value.strip() not in AUTHOR_OK:
                        bad.append(f"{tag}={value}")
    return bad


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser()
    ap.add_argument("--ci", action="store_true", help="不讀清單，只檢查 docx 的作者欄位")
    ap.add_argument("--list", type=Path, default=DEFAULT_LIST, help="禁用字詞清單的位置")
    ap.add_argument("--show", action="store_true", help="命中時印出詞本身和 docx 欄位的值")
    args = ap.parse_args()

    terms: list[str] = []
    if not args.ci:
        if not args.list.is_file():
            print(f"找不到禁用字詞清單：{args.list}\n請建立這個檔案，一行一個客戶名稱、公司名稱或同事名字。")
            return 2
        terms = load_terms(args.list)
        if not terms:
            print(f"禁用字詞清單是空的：{args.list}\n掃描照跑，但沒有字詞可比對，等於只檢查 docx 欄位。")

    try:
        files = repo_files()
    except (subprocess.CalledProcessError, FileNotFoundError) as e:
        print(f"讀不到 git 的檔案清單：{e}")
        return 2

    def name(t: str) -> str:
        return f"「{t}」" if args.show else f"清單第 {terms.index(t) + 1} 個詞"

    def field(b: str) -> str:
        return b if args.show else b.split("=", 1)[0]

    hits: list[str] = []
    for f in files:
        rel = f.relative_to(REPO).as_posix()
        for t in find_terms(rel, terms):
            hits.append(f"{rel}：檔名含{name(t)}")
        if f.suffix.lower() == ".docx":
            hits += [f"{rel}：作者欄位 {field(b)} 不是允許的值" for b in docx_authors(f)]
            text = docx_text(f)
        else:
            text = read_text(f)
            if text is None:
                continue  # 音檔、圖片這類二進位檔
        hits += [f"{rel}：內容含{name(t)}" for t in find_terms(text, terms)]

    if terms:
        try:
            log = git("log", "--all", "--format=%h %B%x00")
        except subprocess.CalledProcessError as e:
            print(f"讀不到 commit 訊息：{e.stderr.strip()}")
            return 2
        for line in log.split("\0"):
            line = line.strip()
            if line:
                hits += [f"commit {line.split()[0]}：訊息含{name(t)}" for t in find_terms(line, terms)]

    mode = "只檢查 docx 欄位" if args.ci else f"{len(terms)} 個禁用字詞"
    if hits:
        print(f"掃描 {len(files)} 個檔案（{mode}），命中 {len(hits)} 處：")
        print("\n".join(f"- {h}" for h in hits))
        return 1
    print(f"掃描 {len(files)} 個檔案（{mode}），沒有命中。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
