@echo off
REM Cognitive Nexus AI - Build Executable
REM Creates a standalone executable using PyInstaller

echo.
echo ========================================
echo   🧠 Cognitive Nexus AI - Build Executable
echo ========================================
echo.

:: Check if Python is installed
python --version >nul 2>&1
if %errorlevel% neq 0 (
    echo ERROR: Python is not installed or not in PATH
    echo Please install Python from https://python.org
    pause
    exit /b 1
)

:: Check if main app file exists
if not exist "cognitive_nexus_ai.py" (
    echo ERROR: cognitive_nexus_ai.py not found
    echo Please run this script from the project directory
    pause
    exit /b 1
)

:: Install PyInstaller if not present
echo Installing PyInstaller...
python -m pip install pyinstaller --quiet --upgrade

:: Clean previous builds
echo Cleaning previous builds...
if exist "build" rmdir /s /q "build"
if exist "dist" rmdir /s /q "dist"

:: Build the executable
echo Building executable...
echo This may take several minutes...
python -m PyInstaller cognitive_nexus_ai.spec --clean --noconfirm

:: Check if build was successful
if exist "dist\CognitiveNexusAI\CognitiveNexusAI.exe" (
    echo.
    echo ========================================
    echo   Build completed successfully!
    echo   Executable: dist\CognitiveNexusAI\CognitiveNexusAI.exe
    echo ========================================
    echo.
    echo Opening build directory...
    explorer "dist\CognitiveNexusAI"
) else (
    echo.
    echo ========================================
    echo   Build failed! Check the output above.
    echo ========================================
    pause
    exit /b 1
)

echo.
echo Build completed! You can now distribute the dist\CognitiveNexusAI folder.
pause