@echo off
chcp 65001 >nul
cd /d "%~dp0"

echo [*] 检查依赖...
python -m pip install -r requirements.txt
if errorlevel 1 goto :fail

echo [*] 抓取浙江组播源并同步到 GitHub...
python rtp\b.py --push
if errorlevel 1 goto :fail

echo [+] 更新完成。
exit /b 0

:fail
echo [-] 执行失败，请查看上方输出。
pause
exit /b 1
