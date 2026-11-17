@echo off
chcp 65001 >nul
title JIZURA 歌词识别工具 - 安装依赖

echo.
echo ==========================================
echo   JIZURA 歌词识别工具 - 安装依赖
echo ==========================================
echo.
echo 正在安装 faster-whisper ...
echo （首次使用需要下载模型文件，请耐心等待）
echo.

pip install faster-whisper --quiet

if %errorlevel% neq 0 (
    echo.
    echo ❌ 安装失败，请检查网络连接
    pause
    exit /b 1
)

echo.
echo ✅ 安装完成！
echo.
echo 现在可以使用了：
echo   方法1: 将音乐文件拖到 "识别歌词.bat" 上
echo   方法2: 双击 "识别歌词.bat" 然后输入路径
echo.
pause
