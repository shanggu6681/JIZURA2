@echo off
setlocal

cd /d "%~dp0"

echo ============================================================
echo   JIZURA 一键更新（保留 AI 歌词功能）
echo ============================================================
echo.

REM ========== 1. 检查 Git ==========
where git >nul 2>&1
if errorlevel 1 (
    echo [错误] 未找到 Git！
    echo 请先安装 Git：https://git-scm.com/download/win
    echo.
    pause
    exit /b 1
)

REM ========== 2. 切换到 AI 功能分支 ==========
echo [1/4] 检查分支...
git checkout feature/ai-lyrics >nul 2>&1
if errorlevel 1 (
    echo [错误] 找不到 feature/ai-lyrics 分支
    echo 请确认你使用的是修改后的版本
    pause
    exit /b 1
)

REM ========== 3. 暂存未提交的改动 ==========
for /f "delims=" %%a in ('git status --porcelain') do set dirty=1
if defined dirty (
    echo [提示] 有未保存的改动，暂存中...
    git stash push -m "update-stash" >nul 2>&1
)

REM ========== 4. 拉取官网最新代码 ==========
echo.
echo [2/4] 拉取官网最新代码...
git fetch origin main
if errorlevel 1 (
    echo.
    echo [错误] 拉取失败！
    echo 可能原因：
    echo   1. 网络不通
    echo   2. 镜像站点挂了
    echo.
    echo 当前远程地址：
    git remote -v
    echo.
    pause
    exit /b 1
)

REM ========== 5. 检查是否有更新 ==========
for /f "delims=" %%a in ('git rev-list --count HEAD..origin/main') do set behind=%%a

if "%behind%"=="0" (
    echo [提示] 已经是最新版本，无需更新
    goto :rebuild
)

echo [提示] 官网有 %behind% 个新提交
echo.

REM ========== 6. 合并（rebase） ==========
echo [3/4] 合并更新（保留 AI 功能）...
echo.
git rebase origin/main
if errorlevel 1 (
    REM 先检查是不是只有 sitemap.xml 冲突（这个文件是自动生成的，可以自动解决）
    for /f "delims=" %%a in ('git diff --name-only --diff-filter=U') do set conflict_files=%%a
    
    if "%conflict_files%"=="sitemap.xml" (
        echo [提示] sitemap.xml 日期冲突，自动解决中...
        git checkout --theirs sitemap.xml
        git add sitemap.xml
        set GIT_EDITOR=true
        git rebase --continue
        if errorlevel 1 (
            echo [错误] 自动解决失败
            goto :conflict_help
        )
        echo [完成] 自动解决成功
        goto :rebase_ok
    )
    
    :conflict_help
    echo.
    echo ============================================================
    echo   [警告] 合并时出现冲突！
    echo ============================================================
    echo.
    echo 解决方法：
    echo   1. 打开下面列出的冲突文件
    echo   2. 找到 "<<<<<<<" 标记的地方，手动选择保留哪边
    echo   3. 保存文件后运行：git add 文件名
    echo   4. 然后运行：git rebase --continue
    echo.
    echo 如果想放弃更新，运行：git rebase --abort
    echo.
    echo 冲突文件：
    git diff --name-only --diff-filter=U
    echo.
    pause
    exit /b 1
)

:rebase_ok
echo.
echo [提示] 合并成功！
echo.

REM ========== 7. 构建 ==========
:rebuild
echo [4/4] 重新构建...
where python >nul 2>&1
if errorlevel 1 (
    echo [提示] 未找到 Python，跳过构建
    echo        可以手动运行：python build.py
    goto :done
)

python build.py
if errorlevel 1 (
    echo [警告] 构建失败，代码已更新但页面可能有问题
    echo        请手动运行：python build.py 查看错误详情
    goto :done
)

echo [完成] 构建成功

REM ========== 8. 完成 ==========
:done
echo.
echo ============================================================
echo   更新完成！
echo ============================================================
echo.
echo 最近更新：
git log --oneline -3
echo.
echo 现在可以用「启动AI版.bat」打开使用了
echo.
pause
