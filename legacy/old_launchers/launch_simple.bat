@echo off
REM Cognitive Nexus AI - Simple Version Launcher
REM Launches the simplified version on port 8503

echo.
echo ========================================
echo   🧠 Cognitive Nexus AI - Simple Version
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

REM Check if simple version file exists
if not exist "cognitive_nexus_simple.py" (
    echo ❌ cognitive_nexus_simple.py not found
    echo Please run this script from the project directory
    pause
    exit /b 1
)

echo ✅ Python detected
echo.

echo 🚀 Starting Simple Version...
echo 📱 The app will open in your browser at http://localhost:8503
echo ⏹️  Press Ctrl+C to stop the server
echo.

python -m streamlit run cognitive_nexus_simple.py --server.port 8503 --server.address localhost --server.headless true

pause

