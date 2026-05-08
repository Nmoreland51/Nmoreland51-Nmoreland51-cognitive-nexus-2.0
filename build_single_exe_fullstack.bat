@echo off
setlocal
cd /d "%~dp0"

echo Installing build dependencies...
python -m pip install --upgrade pip >nul
python -m pip install pyinstaller fastapi "uvicorn[standard]" pydantic requests pillow python-dotenv >nul

echo Cleaning old build artifacts...
if exist build rmdir /s /q build
if exist dist rmdir /s /q dist
if exist CognitiveNexusLocal.spec del /f /q CognitiveNexusLocal.spec

echo Building single EXE...
python -m PyInstaller --onefile --name CognitiveNexusLocal --console ^
  --add-data "fullstack-local\frontend;frontend" ^
  launcher_fullstack.py

if exist "dist\CognitiveNexusLocal.exe" (
  echo.
  echo SUCCESS: dist\CognitiveNexusLocal.exe
  explorer dist
) else (
  echo Build failed.
  exit /b 1
)

endlocal
