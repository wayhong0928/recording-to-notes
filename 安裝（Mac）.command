#!/bin/bash
cd "$(dirname "$0")" || exit 1
export PATH="$HOME/.local/bin:$PATH"
if ! command -v uv >/dev/null 2>&1; then
  echo "第一次安裝：先裝 uv，這是裝 Python 套件的小工具，裝在你的使用者資料夾。"
  curl -LsSf https://astral.sh/uv/install.sh | sh
fi
if ! command -v uv >/dev/null 2>&1; then
  echo "uv 沒裝成功，請把上面的訊息截圖，照 README 的「常見問題」處理。"
  read -r -p "按 Enter 關閉視窗。"
  exit 1
fi
PYTHONPATH="$PWD/app" uv run --no-project --python 3.12 python -m minutes install "$@"
rc=$?
echo
read -r -p "按 Enter 關閉視窗。"
exit $rc
