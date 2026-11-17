@echo off
cd /d "%~dp0"

set PORT=8080
set "PYTHON="

echo.
echo ==========================================
echo   JIZURA + AI歌词识别 服务
echo ==========================================
echo.

REM 自动查找可用的 Python
if "%PYTHON%"=="" if exist "%LOCALAPPDATA%\Programs\Python\Python312\python.exe" (
    "%LOCALAPPDATA%\Programs\Python\Python312\python.exe" -c "import faster_whisper" 2>nul
    if %errorlevel%==0 set "PYTHON=%LOCALAPPDATA%\Programs\Python\Python312\python.exe"
)
if "%PYTHON%"=="" if exist "C:\Python312\python.exe" (
    "C:\Python312\python.exe" -c "import faster_whisper" 2>nul
    if %errorlevel%==0 set "PYTHON=C:\Python312\python.exe"
)
if "%PYTHON%"=="" if exist "%LOCALAPPDATA%\Programs\Python\Python311\python.exe" (
    "%LOCALAPPDATA%\Programs\Python\Python311\python.exe" -c "import faster_whisper" 2>nul
    if %errorlevel%==0 set "PYTHON=%LOCALAPPDATA%\Programs\Python\Python311\python.exe"
)
if "%PYTHON%"=="" if exist "C:\Python311\python.exe" (
    "C:\Python311\python.exe" -c "import faster_whisper" 2>nul
    if %errorlevel%==0 set "PYTHON=C:\Python311\python.exe"
)
if "%PYTHON%"=="" if exist "%LOCALAPPDATA%\Programs\Python\Python310\python.exe" (
    "%LOCALAPPDATA%\Programs\Python\Python310\python.exe" -c "import faster_whisper" 2>nul
    if %errorlevel%==0 set "PYTHON=%LOCALAPPDATA%\Programs\Python\Python310\python.exe"
)
if "%PYTHON%"=="" if exist "C:\Python310\python.exe" (
    "C:\Python310\python.exe" -c "import faster_whisper" 2>nul
    if %errorlevel%==0 set "PYTHON=C:\Python310\python.exe"
)

if "%PYTHON%"=="" (
    echo [错误] 没有找到带 AI 识别库的 Python
    echo.
    echo 请先安装依赖，打开命令提示符运行：
    echo   pip install faster-whisper flask flask-cors
    echo.
    echo 或者安装 Python 3.10+
    echo 下载：https://www.python.org/downloads/
    echo.
    pause
    exit /b 1
)

echo [信息] 使用 Python: %PYTHON%
echo.

REM 检查端口，如果被占用就自动关闭旧的
netstat -ano | findstr ":%PORT%" | findstr LISTENING >nul 2>&1
if %errorlevel%==0 (
    echo [信息] 端口 %PORT% 被占用，正在关闭旧服务...
    for /f "tokens=5" %%a in ('netstat -ano ^| findstr ":%PORT%" ^| findstr LISTENING') do (
        taskkill /F /PID %%a >nul 2>&1
    )
    timeout /t 2 /nobreak >nul
    echo [完成] 旧服务已关闭
    echo.
)

REM 检查依赖
echo [检查] 依赖检查中...
"%PYTHON%" -c "import flask" 2>nul
if %errorlevel% neq 0 (
    echo [安装] 正在安装 flask ...
    "%PYTHON%" -m pip install flask flask-cors
    if %errorlevel% neq 0 (
        echo [错误] 安装失败，请检查网络
        pause
        exit /b 1
    )
)

"%PYTHON%" -c "import faster_whisper" 2>nul
if %errorlevel% neq 0 (
    echo.
    echo [安装] 首次使用：正在安装 AI 语音识别库 ...
    echo （可能需要几分钟，请耐心等待）
    echo.
    "%PYTHON%" -m pip install faster-whisper
    if %errorlevel% neq 0 (
        echo [错误] 安装失败，请检查网络
        pause
        exit /b 1
    )
    echo [完成] 安装成功
    echo.
)

REM 检查 demucs（人声分离，可选，默认不自动安装）
"%PYTHON%" -c "import demucs; import torchaudio" 2>nul
if %errorlevel% neq 0 (
    echo [提示] 人声分离库未安装（可选，提升识别精度）
    echo        如需安装请运行: pip install demucs torchaudio
    echo        GPU加速版: pip install torch torchaudio --index-url https://download.pytorch.org/whl/cu124
    echo.
)

echo [完成] 依赖检查通过
echo.
echo [启动] 正在启动服务...
echo.
echo ==========================================
echo   页面: http://localhost:%PORT%/zh-hans/
echo   关闭窗口即可停止服务
echo ==========================================
echo.

start "" "http://localhost:%PORT%/zh-hans/"
"%PYTHON%" "%~dp0lyrics_tools\server.py"

if %errorlevel% neq 0 (
    echo.
    echo ==========================================
    echo [错误] 服务异常退出
    echo ==========================================
    echo.
    echo 请把上面的错误截图反馈
    echo.
    pause
)
