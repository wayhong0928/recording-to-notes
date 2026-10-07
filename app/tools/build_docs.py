"""把 docs/ 的說明文件合成一個雙擊就能離線打開的 HTML（計畫第 11 節）。

md 是唯一來源，改了 md 就重跑這支，產生的 docs/使用說明.html 一起 commit。安裝時會複製到工作區。

用法（在 app\\ 底下）：
    uv run python tools\\build_docs.py
"""
import html
import re
from pathlib import Path

import markdown

DOCS = Path(__file__).resolve().parents[1] / "docs"
PAGES = ["使用流程.md", "安裝.md", "資料流向.md", "常見問題.md"]
OUT = DOCS / "使用說明.html"

CSS = """
body { font-family: "Microsoft JhengHei", "PingFang TC", "Noto Sans TC", sans-serif; line-height: 1.75;
       max-width: 820px; margin: 0 auto; padding: 24px 16px 80px; color: #1f2328; background: #fff; }
h1 { font-size: 1.9em; border-bottom: 2px solid #d0d7de; padding-bottom: .3em; }
h1.page { margin-top: 2.4em; }
h2 { font-size: 1.35em; margin-top: 1.8em; }
table { border-collapse: collapse; width: 100%; margin: 1em 0; display: block; overflow-x: auto; }
th, td { border: 1px solid #d0d7de; padding: 6px 10px; text-align: left; vertical-align: top; }
th { background: #f6f8fa; }
code { background: #f6f8fa; padding: .1em .35em; border-radius: 4px; font-size: .92em; }
blockquote { margin: 1em 0; padding: .4em 1em; border-left: 4px solid #d4a72c; background: #fff8c5; }
nav { background: #f6f8fa; border-radius: 8px; padding: 12px 20px; }
nav a { margin-right: 1.2em; }
a { color: #0969da; }
@media (prefers-color-scheme: dark) {
  body { color: #e6edf3; background: #0d1117; }
  th, code, nav { background: #161b22; }
  th, td { border-color: #30363d; }
  blockquote { background: #2d2a1a; }
  a { color: #4493f8; }
}
"""


def anchor(name: str) -> str:
    return "page-" + Path(name).stem


def build() -> str:
    nav = " ".join(f'<a href="#{anchor(p)}">{Path(p).stem}</a>' for p in PAGES)
    parts = []
    for i, name in enumerate(PAGES):
        text = (DOCS / name).read_text(encoding="utf-8")
        # 文件之間的連結（安裝.md）換成同一頁的錨點
        for other in PAGES:
            text = text.replace(f"]({other})", f"](#{anchor(other)})")
        body = markdown.markdown(text, extensions=["tables", "fenced_code"])
        body = re.sub(r"^<h1>", f'<h1 id="{anchor(name)}" class="{"page" if i else ""}">', body, count=1)
        parts.append(body)
    return (
        '<!doctype html>\n<html lang="zh-Hant">\n<head>\n<meta charset="utf-8">\n'
        '<meta name="viewport" content="width=device-width, initial-scale=1">\n'
        f"<title>{html.escape('會議紀錄小幫手 使用說明')}</title>\n<style>{CSS}</style>\n</head>\n<body>\n"
        f"<p><strong>會議紀錄小幫手</strong> 使用說明</p>\n<nav>{nav}</nav>\n"
        + "\n".join(parts) + "\n</body>\n</html>\n"
    )


if __name__ == "__main__":
    OUT.write_text(build(), encoding="utf-8", newline="\n")
    print(f"已產生 {OUT}")
