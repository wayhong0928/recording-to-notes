@echo off
chcp 65001 >nul
setlocal
cd /d "%~dp0"
set "PATH=%USERPROFILE%\.local\bin;%PATH%"
where uv >nul 2>nul
if errorlevel 1 (
  echo 第一次安裝：先裝 uv，這是裝 Python 套件的小工具，裝在你的使用者資料夾。
  powershell -NoProfile -ExecutionPolicy Bypass -Command "irm https://astral.sh/uv/install.ps1 | iex"
)
where uv >nul 2>nul
if errorlevel 1 (
  echo uv 沒裝成功，請把上面的訊息截圖，照 README 的「常見問題」處理。
  pause
  exit /b 1
)
set "PYTHONPATH=%~dp0app"
uv run --no-project --python 3.12 python -m minutes install %*
set "RC=%ERRORLEVEL%"
echo.
pause
exit /b %RC%
