@echo off
setlocal
cd /d "%~dp0"

echo ========================================
echo Building FULL PROJECT executable
echo Source: %CD%
echo ========================================

python --version >nul 2>&1
if %errorlevel% neq 0 (
  echo ERROR: Python not found in PATH.
  exit /b 1
)

python -m pip install --upgrade pip
python -m pip install pyinstaller streamlit requests beautifulsoup4 trafilatura psutil

if exist build rmdir /s /q build
if exist dist rmdir /s /q dist

python -m PyInstaller cognitive_nexus_full_project.spec --clean --noconfirm

if exist "dist\CognitiveNexusFullProject\CognitiveNexusFullProject.exe" (
  echo.
  echo SUCCESS:
  echo dist\CognitiveNexusFullProject\CognitiveNexusFullProject.exe
  explorer "dist\CognitiveNexusFullProject"
) else (
  echo.
  echo Build failed.
  exit /b 1
)

endlocal
