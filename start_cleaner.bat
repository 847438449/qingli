@echo off
setlocal

REM 切换到脚本所在目录
cd /d "%~dp0"

REM 优先使用 py 启动器，其次 python
where py >nul 2>nul
if %errorlevel%==0 (
    py -3.11 main.py
    goto :end
)

where python >nul 2>nul
if %errorlevel%==0 (
    python main.py
    goto :end
)

echo [ERROR] 未找到 Python，请先安装 Python 3.11+ 并加入 PATH。
pause

:end
endlocal
