# AGENTS.md

給 AI 助理（Claude Code、Codex 等）看的說明。使用者說「幫我下載／安裝這個 repo」時照第 1 節做；要改程式時看第 2 節。跟使用者講話一律用中文白話，不貼指令細節。

## 1. 幫使用者安裝

這個工具在使用者的電腦上把會議錄音轉成逐字稿，再用 Claude Code 的 `/會議紀錄` 整理成 Word。安裝不需要管理員權限。

1. 取得 repo：有 git 就 `git clone <repo 網址>`，沒有就下載 ZIP 解壓縮。放在哪裡都可以，安裝會把程式複製到固定位置，之後這個資料夾可以刪。
2. 跟使用者說明接下來會做的事，取得同意後再裝：會下載約 1 GB 的 Python 套件和約 3 GB 的語音辨識模型，有 NVIDIA 顯卡再加約 1.5 GB；工作區建在使用者資料夾底下的 `會議紀錄`；桌面會多一個捷徑。
3. 確認有 uv（`uv --version`）。沒有就裝到使用者目錄：
   - Windows（PowerShell）：`powershell -ExecutionPolicy Bypass -c "irm https://astral.sh/uv/install.ps1 | iex"`
   - Mac：`curl -LsSf https://astral.sh/uv/install.sh | sh`
   - 裝完後 uv 在 `~/.local/bin`，當下的 shell 可能還找不到，先加進 PATH：PowerShell 用 `$env:Path = "$HOME\.local\bin;$env:Path"`，Mac／Git Bash 用 `export PATH="$HOME/.local/bin:$PATH"`。
4. 在 repo 根目錄跑安裝，`--yes` 是不等使用者按 Enter：
   - Windows（PowerShell）：`$env:PYTHONPATH = "$PWD\app"; uv run --no-project --python 3.12 python -m minutes install --yes`
   - Mac／Git Bash：`PYTHONPATH="$PWD/app" uv run --no-project --python 3.12 python -m minutes install --yes`
   - 雙擊用的 `安裝（Windows）.bat`、`安裝（Mac）.command` 做的是同一件事，但最後會等按鍵，AI 助理直接跑上面的指令就好。
   - 下載模型要幾分鐘到半小時，指令的逾時要設長一點（至少 30 分鐘），或放到背景跑。
5. 看結果：最後印出「安裝完成」就成功。失敗時畫面會寫是哪一步，完整記錄在程式資料夾的 `logs/install.log`（Windows：`%LOCALAPPDATA%\MeetingMinutes\`，Mac：`~/Library/Application Support/MeetingMinutes/`）。修好後重跑同一個指令就好，已經下載好的模型不會重新下載。
6. 告訴使用者怎麼用：錄音放進 `會議紀錄\錄音放這裡`，在 `會議紀錄` 資料夾打開 Claude Code，輸入 `/會議紀錄`。第一次用會跳權限詢問，選「Yes, and don't ask again」之後就不會一直問。

常見狀況：
- 安裝前檢查有「問題」的項目（例如硬碟空間不夠）會直接停下來，照畫面上的「怎麼修」處理。
- 顯示卡驅動太舊時會先用 CPU 裝好，請使用者更新驅動後再跑一次安裝。
- 沒有 Claude Code 只會出現「注意」，安裝照樣完成，但要裝好 Claude Code 才能用 `/會議紀錄`。

## 2. 開發

- 程式都在 `app/`，用 uv 和 Python 3.12，指令都在 `app/` 底下跑：`uv sync`、`uv run pytest`、`uv run minutes -h`。
- 程式碼的資料夾一律用英文；使用者會看到的（工作區、會議資料夾裡的檔案、使用者會打開的文件、安裝檔）才用中文。
- 所有訊息、說明文件都用中文（台灣用語）。`minutes` 指令加 `--json` 時印給 skill 讀的 JSON，`ok` 和 `error` 欄位的格式要一致。
- 去識別化：repo 裡（程式、公版、範例、文件、測試、commit 訊息）不能出現真實的客戶名、公司名、人名、手機品牌，範例一律用虛構的。改完在 `app/` 跑 `uv run python tools/check_names.py`；禁用字詞清單在 `private/`，不進版控，不要讀它的內容。
- 改了 `app/docs/` 的 md，要跑 `uv run python tools/build_docs.py` 重新產生 `使用說明.html`。
- `/會議紀錄` 的 skill 在 `app/workspace_template/.claude/skills/會議紀錄/`，安裝時把 `{{MINUTES}}` 換成程式路徑；整理規則和問答式公版在 `app/templates/content/`，安裝時複製進 skill 資料夾。
- `.gitignore` 自己加的規則只列 pattern，不寫註解。
