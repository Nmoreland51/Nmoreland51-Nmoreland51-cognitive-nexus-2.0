@echo off
REM Cognitive Nexus AI - Main Launcher
REM Opens in Microsoft Edge browser

echo.
echo ========================================
echo   🧠 Cognitive Nexus AI - Launcher
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

REM Check if main app file exists
if not exist "cognitive_nexus_ai.py" (
    echo ❌ cognitive_nexus_ai.py not found!
    echo Please run this script from the project directory
    pause
    exit /b 1
)

echo 🚀 Starting Cognitive Nexus AI...
echo 📱 The app will open in Microsoft Edge at http://localhost:8501
echo ⏹️  Press Ctrl+C to stop the server
echo.

REM Start browser opening in background (delayed)
start /b cmd /c "timeout /t 8 /nobreak >nul 2>&1 && (
    if exist \"%ProgramFiles(x86)%\\Microsoft\\Edge\\Application\\msedge.exe\" (
        \"%ProgramFiles(x86)%\\Microsoft\\Edge\\Application\\msedge.exe\" \"http://localhost:8501\"
    ) else if exist \"%ProgramFiles%\\Microsoft\\Edge\\Application\\msedge.exe\" (
        \"%ProgramFiles%\\Microsoft\\Edge\\Application\\msedge.exe\" \"http://localhost:8501\"
    ) else if exist \"%LOCALAPPDATA%\\Microsoft\\Edge\\Application\\msedge.exe\" (
        \"%LOCALAPPDATA%\\Microsoft\\Edge\\Application\\msedge.exe\" \"http://localhost:8501\"
    ) else (
        start http://localhost:8501
    )
)"

REM Run Streamlit in foreground (user can see output and stop with Ctrl+C)
python -m streamlit run cognitive_nexus_ai.py --server.port 8501 --server.address localhost --server.headless true --browser.gatherUsageStats false
