@echo off
chcp 65001 >nul
title JIZURA 歌词识别工具

REM 检查是否有拖入的文件
if "%~1"=="" (
    REM 没有拖入文件，进入交互模式
    python "%~dp0transcribe_lyrics.py"
) else (
    REM 有拖入的文件，直接识别（默认 small 模型，自动语言）
    echo.
    echo ==========================================
    echo   JIZURA 歌词识别工具
    echo ==========================================
    echo.
    echo 正在识别: %~nx1
    echo.
    python "%~dp0transcribe_lyrics.py" "%~1" --model small
)

echo.
pause
