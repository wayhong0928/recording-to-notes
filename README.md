# recording-to-notes（會議紀錄小幫手）

把會議錄音變成 Word 會議紀錄。錄音在你自己的電腦上轉成逐字稿，不上傳；再由 Claude 整理成問答式的會議紀錄，產生 Word 檔。

- **安裝**：下載 ZIP、解壓縮，雙擊 `安裝（Windows）.bat`（Mac 是 `安裝（Mac）.command`）。也可以直接跟 Claude Code 或 Codex 說「請下載這個 repo 並安裝」，附上這頁的網址，它會照 [AGENTS.md](AGENTS.md) 裝好。
- **需要**：[Claude Code](https://code.claude.com/docs)，用付費方案（Pro 以上）的帳號登入。
- **錄音格式**：m4a、wav 實際測過；mp3、flac、ogg、mp4、webm 應該可以，沒有逐一測過。

## 怎麼用

1. 錄音放進工作區的 `錄音放這裡` 資料夾（工作區在使用者資料夾底下的 `會議紀錄`，桌面有捷徑）。
2. 在工作區打開 Claude Code，輸入 `/會議紀錄`。
3. 回答會議名稱等幾個問題，等 Word 打開。

一場會議錄成好幾段沒關係，程式會依錄音的開始時間排好、合併。要修改就在對話裡跟 Claude 說，它會產生新一版 Word，舊的留著。

詳細說明在 `app\docs\`，安裝後工作區也有一份 `使用說明.html`：

- [使用流程](app/docs/使用流程.md)：Claude 會問什麼、產出哪些檔案、怎麼修改、權限詢問怎麼選
- [安裝](app/docs/安裝.md)：需要準備什麼、裝在哪裡、更新和移除
- [資料流向](app/docs/資料流向.md)：哪些資料會離開你的電腦
- [常見問題](app/docs/常見問題.md)

## 資料會送到哪裡

錄音只在你的電腦上轉逐字稿。**整理成會議紀錄那一步會把逐字稿送到 Claude（Anthropic 的雲端服務）。** 處理客戶或公司的會議之前，先確認公司和客戶的規定允許這樣做。詳見[資料流向](app/docs/資料流向.md)。

## 測試範圍

v0.1.0 只在一台 Windows 11 筆電（RTX 5060 Laptop）上測過：

- 安裝檔從頭到尾實際跑過（含顯示卡加速套件、合成語音試跑），重跑一次也沒問題。
- 在終端機版 Claude Code 跑 `/會議紀錄`：三段手機錄音（共約 1 小時 40 分）合併轉逐字稿、整理成會議紀錄、產生 Word。
- 單元測試涵蓋錄音分組（含跨午夜）、合併、Word 產生、Word 被改過的提醒、顯示卡失敗改用 CPU 等。GitHub Actions 在 Windows 和 Mac 上跑單元測試。

**沒有測過**：

- Mac 的安裝和使用（安裝檔照同樣設計寫好，但沒在 Mac 上跑過）。
- Claude 桌面版（Code 分頁）：權限詢問會跳幾次、長時間的背景轉錄會不會中斷。
- 沒有獨立顯示卡的一般筆電的速度。
- Windows 帳號名稱是中文的電腦。
- 從 GitHub 下載的 ZIP 被 SmartScreen 攔下的實際畫面、模型下載中斷後接著下載。

## 用到的套件與模型

| 名稱 | 用途 | 授權 |
|---|---|---|
| [faster-whisper](https://github.com/SYSTRAN/faster-whisper) | 語音轉文字 | MIT |
| [CTranslate2](https://github.com/OpenNMT/CTranslate2) | 模型推論 | MIT |
| [PyAV](https://github.com/PyAV-Org/PyAV) | 讀錄音檔 | BSD-3-Clause |
| [opencc-python-reimplemented](https://github.com/yichen0831/opencc-python) | 簡體轉正體 | Apache-2.0 |
| [docxtpl](https://github.com/elapouya/python-docx-template) | 套 Word 公版 | LGPL-2.1 |
| [python-docx](https://github.com/python-openxml/python-docx) | 產生 Word | MIT |
| [huggingface_hub](https://github.com/huggingface/huggingface_hub) | 下載模型 | Apache-2.0 |
| [uv](https://github.com/astral-sh/uv) | 安裝 Python 和套件 | MIT 或 Apache-2.0 |
| [Breeze-ASR-25](https://huggingface.co/MediaTek-Research/Breeze-ASR-25)（聯發科，Whisper large-v2 微調） | 預設模型，台灣華語和中英夾雜 | Apache-2.0 |
| [phate334/Breeze-ASR-25-ct2](https://huggingface.co/phate334/Breeze-ASR-25-ct2) | 上面那個模型的 CTranslate2 轉檔版，實際下載的是這個 | Apache-2.0 |
| [faster-whisper-large-v3-turbo](https://huggingface.co/mobiuslabsgmbh/faster-whisper-large-v3-turbo) | 選用的快速模式 | MIT |
| [faster-whisper-large-v3](https://huggingface.co/Systran/faster-whisper-large-v3) | 選用 | MIT |

授權是 2026-10-07 從各套件的 PyPI 資料和 Hugging Face 模型頁查的。

## 開發

程式都在 `app\`，用 [uv](https://docs.astral.sh/uv/) 管理 Python 3.12 和套件。以下指令都在 `app\` 底下執行。

```powershell
uv sync                 # 只用 CPU
uv sync --extra gpu     # 有 NVIDIA 顯卡：另外裝 pip 版的 cuBLAS、cuDNN
uv run pytest           # 單元測試（不需要模型和顯卡）
uv run minutes -h       # 指令說明
```

開發時可以用環境變數換位置：`MINUTES_HOME` 換程式資料夾，`MINUTES_WORKSPACE` 換工作區。

### 指令

只有 Claude 和安裝檔會打這些指令。每個指令都用中文印出結果，加 `--json` 改印給 skill 讀的 JSON。

```powershell
uv run minutes check [--quick] [--before-install]   # 只檢查不安裝
uv run minutes install [--yes]                       # 安裝（安裝檔呼叫的就是這個）
uv run minutes scan                                  # 列出「錄音放這裡」的錄音，依開始時間分組
uv run minutes new <會議名稱> <錄音…> --date YYYY-MM-DD [--to <資料夾>]
uv run minutes transcribe <會議資料夾> [--model breeze|turbo|large-v3] [--device auto|cuda|cpu]
uv run minutes render <會議資料夾> [--no-open]       # 2_會議紀錄.md 轉成 Word
uv run minutes word-status <會議資料夾>              # 最新一版 Word 有沒有被改過
uv run minutes version
```

- 錄音的開始時間先看檔名（例如 `語音 YYMMDD_HHMMSS`、`YYYYMMDD_HHMMSS`），再看檔內的建立時間，最後看檔案修改時間；後兩種標成時間不確定。同一天的錄音分在同一組，兩段之間空 1 小時以上會標出來，不會自動拆開。不同天的錄音空 1 小時以上才分成兩組；不到 1 小時的（例如過了午夜才結束的會議）算同一組，過了午夜的時間標「（隔天）」。
- `transcribe` 每段分開轉，結果存在會議資料夾的 `_暫存\`，中斷後重跑只轉沒做完的段落，最後合併成 `1_逐字稿.md`。會議資料夾裡有 `0_名單與術語.txt` 時，內容當作提示文字。
- `--device auto`：有 NVIDIA 顯卡、驅動夠新、裝了 GPU 套件就用顯卡，不然用 CPU。用顯卡失敗時自動改用 CPU 重轉那一段。Mac 一律用 CPU。
- `render` 每次產生一份新的 `2_會議紀錄_年月日時分秒.docx`，舊的不刪。最新一版被改過時只提醒，照樣產生。

### 檔案

| 位置 | 內容 |
|---|---|
| `安裝（Windows）.bat`、`安裝（Mac）.command` | 確認有 uv，再用 uv 的 Python 跑 `minutes install` |
| `app/minutes/` | Python 套件 |
| `app/templates/` | Word 公版、問答式內容公版、整理規則、範例 |
| `app/workspace_template/` | 工作區範本，安裝時複製過去，`{{MINUTES}}` 換成程式路徑 |
| `app/docs/` | 說明文件；`uv run python tools\build_docs.py` 把它們合成 `使用說明.html` |
| `app/eval/` | 轉錄評測 |
| `app/tools/check_names.py` | 去識別化檢查 |

### 評測

測試集腳本放在 `eval\testset\`，內容是虛構的。腳本裡用 `{文字|類別}` 標記關鍵資訊（neg 否定、num 數字、date 日期時間、name 人名、en 英文）。

```powershell
# 1. 用 Windows 內建的台灣中文語音合成音檔（離線），輸出到 eval\out\testset\<名稱>\
uv run python eval\build_testset.py eval\testset\meeting_01.txt
# 2. 轉錄並計分，報告寫到 eval\out\testset\<名稱>\report.md；加 --reuse 只重算分數
uv run python eval\evaluate.py meeting_01 --models large-v3 large-v3-turbo breeze
```

報告的欄位：混合錯誤率（中文一字、英文一詞算一個單位，數字轉成中文讀法再比）、各類關鍵資訊答對幾個、多出的否定詞、跟前一段完全相同的重複段落數、耗時。「八五折／85折」「三成／30%」這類同義寫法會被判成不同，關鍵資訊錯誤要回原句看一眼。

### 去識別化檢查

repo 裡不能出現客戶名稱、公司名稱、同事名字。禁用字詞清單放在 repo 根目錄的 `private\禁用字詞.txt`（不進版控），每次 commit 前跑：

```powershell
uv run python tools\check_names.py
```

## 授權

[MIT](LICENSE)
