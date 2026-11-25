@echo off
rem ============================================================
rem  DeShelf / Juanzhi - build single-file EXE with PyInstaller
rem  Uses the .spec file in this folder (卷帙.spec).
rem  Output: dist\卷帙.exe
rem
rem  The script also guards two Windows/IDE traps that otherwise break
rem  "PyInstaller --clean" (see the two blocks below for details).
rem
rem  Usage:  build.bat              (build, keeps window open)
rem          build.bat /nopause    (build, no pause, for scripts)
rem ============================================================
setlocal
chcp 65001 >nul
cd /d "%~dp0"
set "RC=0"

rem --- Trap 1: IDE-injected sitecustomize -------------------------------
rem PyCharm's copilot plugin puts its own sitecustomize.py on PYTHONPATH
rem and that shim reroutes os.remove() to the recycle bin. Under it,
rem "--clean" never really deletes the old build tree, and the build dies
rem while deleting dist\*.exe with: SHFileOperationW failed 0x7c.
set "PYTHONPATH="

rem --- Interpreter: prefer the project virtualenv -----------------------
rem PyInstaller lives in .venv; a bare "python" on PATH may be a different
rem install that has no PyInstaller at all.
set "PY=python"
if exist ".venv\Scripts\python.exe" set "PY="%CD%\.venv\Scripts\python.exe""
%PY% -c "import sys" >nul 2>&1
if errorlevel 1 set "PY=py -3"
%PY% -c "import sys" >nul 2>&1
if errorlevel 1 (
    echo [ERROR] Python not found in PATH.
    goto :fail
)

echo [1/4] Locating spec file ...
set "SPEC="
for %%f in ("*.spec") do (
    if defined SPEC (
        echo [ERROR] More than one .spec file in "%CD%" - keep only the one to build.
        goto :fail
    )
    set "SPEC=%%~ff"
)
if not defined SPEC (
    echo [ERROR] No .spec file found in "%CD%".
    goto :fail
)
echo       %SPEC%

echo [2/4] Checking PyInstaller ...
%PY% -m PyInstaller --version >nul 2>&1
if errorlevel 1 (
    echo [ERROR] PyInstaller is not installed for "%PY%".
    echo         Run:  %PY% -m pip install -r requirements.txt
    goto :fail
)

echo [3/4] Closing a running instance ...
rem --- Trap 2: onefile leaves two processes -----------------------------
rem A running (or half-killed) 卷帙.exe keeps a lock on dist\卷帙.exe and
rem the next build fails with: PermissionError [WinError 5]. onefile apps
rem use a parent bootloader + child process, so kill by image name.
if exist "dist\*.exe" for %%e in ("dist\*.exe") do taskkill /f /im "%%~nxe" >nul 2>&1
rem Give Windows a moment to release the file handle.
ping -n 2 127.0.0.1 >nul

echo [4/4] Building, please wait ...
%PY% -m PyInstaller --noconfirm --clean "%SPEC%"
if errorlevel 1 (
    echo.
    echo [ERROR] Build failed, see the log above.
    goto :fail
)

echo.
echo [OK] Build finished. Output folder: "%CD%\dist"
for %%e in ("dist\*.exe") do echo      %%~nxe   (%%~ze bytes)
goto :finish

:fail
set "RC=1"
echo.
echo [FAIL] Build aborted.

:finish
endlocal & set "RC=%RC%"
if /i not "%~1"=="/nopause" pause
exit /b %RC%
