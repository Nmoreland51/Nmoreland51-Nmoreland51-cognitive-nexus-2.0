@echo off
REM Cognitive Nexus AI - Install Image Generation Dependencies
REM Installs packages required for AI image generation

echo.
echo ========================================
echo   🎨 Image Generation Dependencies
echo ========================================
echo.
echo This will install the required packages for image generation:
echo - torch (PyTorch for AI models)
echo - diffusers (Hugging Face Diffusers library)
echo - pillow (Image processing)
echo - transformers (Hugging Face Transformers)
echo - accelerate (Model acceleration)
echo - safetensors (Safe tensor format)
echo.
echo Note: This may take several minutes and download ~4GB of data.
echo.
pause

echo.
echo 📦 Installing packages...
pip install torch diffusers pillow transformers accelerate safetensors

echo.
echo ✅ Installation complete!
echo.
echo 🚀 You can now run the advanced version with image generation:
echo    python -m streamlit run cognitive_nexus_advanced.py --server.port 8504
echo.
echo Or use the launcher:
echo    run_advanced_cognitive_nexus.bat
echo.
pause
