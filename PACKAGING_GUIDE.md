# 📦 Cognitive Nexus AI - Packaging Guide

This guide explains how to package your Cognitive Nexus AI app into a standalone executable.

## 🚀 Quick Start

### 1. One-Click Build
```bash
# Simply run the build script
build_executable.bat
```

### 2. Manual Build
```bash
# Install PyInstaller
pip install pyinstaller

# Build executable
pyinstaller cognitive_nexus_ai.spec --clean
```

## 📁 File Structure

```
cognitive_nexus_ai/
├── cognitive_nexus_ai.py      # Main app
├── run.py                     # Executable wrapper
├── cognitive_nexus_ai.spec    # PyInstaller config
├── build_executable.bat       # Build script
├── version.py                 # Version management
├── update_changelog.py        # Changelog automation
└── dist/CognitiveNexusAI/     # Built executable
    └── CognitiveNexusAI.exe   # Your app!
```

## 🔄 Update Workflow

### When you make changes:

1. **Update your code** - Edit `cognitive_nexus_ai.py` or other files
2. **Update version** - Modify `version.py` with new version number
3. **Generate changelog** - Run `python update_changelog.py`
4. **Rebuild executable** - Run `build_executable.bat`
5. **Test** - Run the new executable
6. **Distribute** - Share the `dist/CognitiveNexusAI/` folder

## 📋 Features Included

- ✅ **Standalone executable** - No Python installation required
- ✅ **All dependencies bundled** - Including Streamlit, PyTorch, etc.
- ✅ **Automatic changelog** - Version tracking and release notes
- ✅ **One-click build** - Simple batch script automation
- ✅ **Cross-platform** - Works on Windows (can be adapted for Mac/Linux)

## 🛠️ Customization

### Change App Icon
1. Add `icon.ico` file to your project
2. The spec file will automatically use it

### Add More Files
Edit `cognitive_nexus_ai.spec` and add to `datas` section:
```python
datas=[
    ('your_file.txt', '.'),
    ('your_folder', 'your_folder'),
],
```

### Exclude Dependencies
Add unwanted modules to `excludes` in the spec file.

## 🎯 Distribution

The built executable is in `dist/CognitiveNexusAI/`. You can:
- **Zip the folder** and share it
- **Create an installer** using tools like Inno Setup
- **Upload to GitHub Releases** for easy distribution

## 🔧 Troubleshooting

### Build Fails
- Check Python installation
- Ensure all dependencies are installed
- Review error messages in console

### Executable Won't Start
- Run from command line to see errors
- Check if all required files are included
- Verify paths in the spec file

### Missing Dependencies
Add missing imports to `hiddenimports` in the spec file.

---

**Happy packaging!** 🎉
