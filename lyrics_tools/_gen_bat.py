# -*- coding: utf-8 -*-
"""生成 GBK 编码的 bat 文件"""
import os

def write_bat(filename, content):
    """以 GBK 编码写入 bat 文件"""
    path = os.path.join(r'd:\app\JIZURA', filename)
    with open(path, 'w', encoding='gbk', errors='replace') as f:
        f.write(content)
    print(f'✅ 已生成: {filename}')

# ===== 关闭服务.bat =====
close_bat = '''@echo off
title 关闭 JIZURA 服务

echo.
echo ==========================================
echo   关闭 JIZURA 服务
echo ==========================================
echo.

set FOUND=0
for /f "tokens=5" %%a in ('netstat -ano ^| findstr :8080 ^| findstr LISTENING') do (
    echo 找到进程 PID: %%a
    taskkill /F /PID %%a >nul 2>&1
    if %%errorlevel%%==0 (
        echo [成功] 已关闭进程 %%a
    ) else (
        echo [警告] 关闭失败
    )
    set FOUND=1
)

if %%FOUND%%==0 (
    echo [提示] 端口 8080 没有被占用，服务未在运行
) else (
    echo.
    echo [完成] 服务已关闭
)

echo.
pause
'''

# ===== 启动AI版.bat =====
start_bat = '''@echo off
cd /d "%~dp0"

set PORT=8080
set "PYTHON="

echo.
echo ==========================================
echo   JIZURA + AI歌词识别 服务
echo ==========================================
echo.

REM === 0. 查找 Python（优先用装了 faster-whisper 的） ===
REM 先试试常见安装路径
if exist "C:\\Python312\\python.exe" (
    "C:\\Python312\\python.exe" -c "import faster_whisper" 2>nul
    if %%errorlevel%%==0 set "PYTHON=C:\\Python312\\python.exe"
)
if "%PYTHON%"=="" if exist "C:\\Python311\\python.exe" (
    "C:\\Python311\\python.exe" -c "import faster_whisper" 2>nul
    if %%errorlevel%%==0 set "PYTHON=C:\\Python311\\python.exe"
)
if "%PYTHON%"=="" if exist "C:\\Python310\\python.exe" (
    "C:\\Python310\\python.exe" -c "import faster_whisper" 2>nul
    if %%errorlevel%%==0 set "PYTHON=C:\\Python310\\python.exe"
)
if "%PYTHON%"=="" if exist "%LOCALAPPDATA%\\Programs\\Python\\Python312\\python.exe" (
    "%LOCALAPPDATA%\\Programs\\Python\\Python312\\python.exe" -c "import faster_whisper" 2>nul
    if %%errorlevel%%==0 set "PYTHON=%LOCALAPPDATA%\\Programs\\Python\\Python312\\python.exe"
)
if "%PYTHON%"=="" if exist "%LOCALAPPDATA%\\Programs\\Python\\Python311\\python.exe" (
    "%LOCALAPPDATA%\\Programs\\Python\\Python311\\python.exe" -c "import faster_whisper" 2>nul
    if %%errorlevel%%==0 set "PYTHON=%LOCALAPPDATA%\\Programs\\Python\\Python311\\python.exe"
)
REM 最后试试 PATH 里的 python
if "%PYTHON%"=="" (
    where python >nul 2>&1
    if %%errorlevel%%==0 (
        python -c "import faster_whisper" 2>nul
        if %%errorlevel%%==0 (
            for /f "delims=" %%a in ('where python ^| findstr /i python.exe') do (
                if "%PYTHON%"=="" set "PYTHON=%%a"
            )
        )
    )
)

if "%PYTHON%"=="" (
    echo [错误] 没有找到带 AI 识别库的 Python！
    echo.
    echo 请运行以下命令安装依赖:
    echo   python -m pip install faster-whisper flask flask-cors
    echo.
    echo 或者安装 Python 3.10+，安装时勾选 "Add Python to PATH"
    echo 下载地址: https://www.python.org/downloads/
    echo.
    pause
    exit /b 1
)

echo [信息] 使用 Python: %PYTHON%
echo.

REM === 1. 检查端口是否被占用 ===
netstat -ano | findstr ":%PORT%" | findstr LISTENING >nul 2>&1
if %%errorlevel%%==0 (
    echo [警告] 端口 %PORT% 已被占用！
    echo.
    echo 可能是已经启动了一个 JIZURA 服务。
    echo 请先双击 "关闭服务.bat" 关闭后再试，
    echo 或者直接在浏览器打开 http://localhost:%PORT%/zh-hans/
    echo.
    for /f "tokens=5" %%a in ('netstat -ano ^| findstr :%PORT% ^| findstr LISTENING') do (
        echo 占用进程 PID: %%a
    )
    echo.
    pause
    exit /b 1
)

REM === 2. 检查依赖 ===
echo [检查] 依赖检查中...
"%PYTHON%" -c "import flask" 2>nul
if %%errorlevel%% neq 0 (
    echo [安装] 正在安装 flask ...
    "%PYTHON%" -m pip install flask flask-cors
    if %%errorlevel%% neq 0 (
        echo [错误] flask 安装失败，请检查网络
        pause
        exit /b 1
    )
)

"%PYTHON%" -c "import faster_whisper" 2>nul
if %%errorlevel%% neq 0 (
    echo.
    echo [安装] 首次使用：正在安装 faster-whisper（AI 语音识别库）...
    echo （这可能需要几分钟，请耐心等待）
    echo.
    "%PYTHON%" -m pip install faster-whisper
    if %%errorlevel%% neq 0 (
        echo [错误] faster-whisper 安装失败，请检查网络连接
        echo.
        echo 如果网络不好，可以尝试:
        echo   %PYTHON% -m pip install faster-whisper -i https://pypi.tuna.tsinghua.edu.cn/simple
        echo.
        pause
        exit /b 1
    )
    echo [完成] faster-whisper 安装成功！
    echo.
)

echo [完成] 依赖检查通过
echo.

REM === 3. 启动服务 ===
echo [启动] 正在启动 JIZURA 服务...
echo.
echo ==========================================
echo   页面地址: http://localhost:%PORT%/zh-hans/
echo   关闭此窗口即可停止服务
echo ==========================================
echo.

REM 启动浏览器
start "" "http://localhost:%PORT%/zh-hans/"

REM 启动 Flask 服务
"%PYTHON%" "%~dp0lyrics_tools\server.py"

REM 如果服务异常退出，显示错误
if %%errorlevel%% neq 0 (
    echo.
    echo ==========================================
    echo [错误] 服务异常退出（错误码: %%errorlevel%%）
    echo ==========================================
    echo.
    echo 请把上面的错误信息截图反馈一下。
    echo.
    echo 常见问题:
    echo   1. 端口被占用 - 双击 "关闭服务.bat" 后重试
    echo   2. 依赖缺失 - 重新运行本脚本会自动安装
    echo   3. 模型下载失败 - 检查网络连接
    echo.
    pause
)
'''

write_bat('关闭服务.bat', close_bat)
write_bat('启动AI版.bat', start_bat)
print('\n全部完成！')
