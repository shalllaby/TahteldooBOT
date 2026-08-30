@echo off
chcp 65001 > nul

echo ==========================================================
echo   TahtElDooPublisher - Build v3.0
echo ==========================================================
echo.

:: Step 1: PyInstaller
echo [1/2] Building EXE with PyInstaller...
echo ----------------------------------------------------------
python build_exe.py
if %errorlevel% neq 0 (
    echo.
    echo ERROR: PyInstaller build failed! Check errors above.
    pause
    exit /b 1
)
echo.
echo [OK] EXE built successfully!
echo.

:: Step 2: Inno Setup
echo [2/2] Building Setup installer...
echo ----------------------------------------------------------

set ISCC=
if exist "C:\Program Files (x86)\Inno Setup 6\ISCC.exe" set ISCC=C:\Program Files (x86)\Inno Setup 6\ISCC.exe
if exist "C:\Program Files\Inno Setup 6\ISCC.exe" set ISCC=C:\Program Files\Inno Setup 6\ISCC.exe

if not defined ISCC (
    echo.
    echo WARNING: Inno Setup not found!
    echo Download from: https://jrsoftware.org/isdl.php
    echo Then run this script again.
    echo.
    echo EXE is ready at:
    echo   dist\TahtElDooPublisher\TahtElDooPublisher.exe
    echo.
    explorer dist\TahtElDooPublisher
    pause
    exit /b 0
)

"%ISCC%" "installer\setup.iss"
if %errorlevel% neq 0 (
    echo ERROR: Inno Setup build failed!
    pause
    exit /b 1
)

echo.
echo ==========================================================
echo   BUILD COMPLETE! v3.0
echo   Installer: dist\TahtElDooPublisher_Setup_v3.0.exe
echo ==========================================================
echo.

explorer dist

pause
