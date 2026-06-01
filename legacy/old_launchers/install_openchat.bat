@echo off
REM Cognitive Nexus AI - Install OpenChat Dependencies
REM Installs OpenChat-v3.5 and required packages

title Install OpenChat Dependencies
color 0A

echo.
echo ========================================
echo   🤖 OpenChat-v3.5 Installation
echo ========================================
echo.

REM Check if Python is available
python --version >nul 2>&1
if errorlevel 1 (
    echo ❌ Python not found! Please install Python first.
    echo Download from: https://python.org
    pause
    exit /b 1
)

echo ✅ Python detected
echo.

echo 📦 Installing OpenChat dependencies...
echo This may take several minutes (downloading ~3GB model)...
echo.

REM Install dependencies
pip install torch transformers accelerate bitsandbytes safetensors

if errorlevel 1 (
    echo ⚠️  Some dependencies failed to install
    echo The app will still try to run with available packages
) else (
    echo ✅ OpenChat dependencies installed successfully
)

echo.
echo 🚀 OpenChat-v3.5 is ready!
echo The model will be downloaded automatically on first use.
echo.
pause
