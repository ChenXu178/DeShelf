@echo off
rem ============================================================
rem  DeShelf / Juanzhi - build single-file EXE with PyInstaller
rem  Uses the .spec file in this folder (卷帙.spec).
rem  Output: dist\卷帙.exe
rem
rem  Usage:  build.bat              (build, keeps window open)
rem          build.bat /nopause    (build, no pause, for scripts)
rem ============================================================
setlocal
chcp 65001 >nul
cd /d "%~dp0"
set "RC=0"

set "PY=python"
%PY% -c "import sys" >nul 2>&1
if errorlevel 1 set "PY=py -3"
%PY% -c "import sys" >nul 2>&1
if errorlevel 1 (
    echo [ERROR] Python not found in PATH.
    goto :fail
)

echo [1/3] Locating spec file ...
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

echo [2/3] Checking PyInstaller ...
%PY% -m PyInstaller --version >nul 2>&1
if errorlevel 1 (
    echo [ERROR] PyInstaller is not installed for "%PY%".
    echo         Run:  %PY% -m pip install -r requirements.txt
    goto :fail
)

echo [3/3] Building, please wait ...
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
