@echo off
chcp 65001 >nul
setlocal
set "SCRIPT=%~dp0run_update.bat"

echo [*] 将注册 Windows 计划任务：每两天 09:00 运行 %SCRIPT%
echo [*] 注意：如果已启用 GitHub Actions 定时更新，请二选一，避免重复抓取。
echo.

echo "%SCRIPT%" | find " " >nul
if not errorlevel 1 (
    echo [!] 仓库路径包含空格，schtasks 无法直接注册。
    echo     请把仓库移到无空格路径，或在“任务计划程序”里手动创建任务。
    pause
    exit /b 1
)

schtasks /Create /TN "IPTV-ZJ-2Days" /TR "%SCRIPT%" /SC DAILY /MO 2 /ST 09:00 /F
if errorlevel 1 (
    echo [-] 注册失败，请右键“以管理员身份运行”后重试。
) else (
    echo [+] 注册成功。可用 schtasks /Query /TN "IPTV-ZJ-2Days" 查看，
    echo     或用 schtasks /Delete /TN "IPTV-ZJ-2Days" /F 取消。
)
pause
