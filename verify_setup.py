#!/usr/bin/env python3
"""
Verification script for Cognitive Nexus AI packaging setup
Checks if all required files and dependencies are in place
"""

import os
import sys
from pathlib import Path

def check_file_exists(filepath, description):
    """Check if a file exists and report status"""
    if os.path.exists(filepath):
        print(f"✅ {description}: {filepath}")
        return True
    else:
        print(f"❌ {description}: {filepath} - NOT FOUND")
        return False

def check_python_import(module_name, description):
    """Check if a Python module can be imported"""
    try:
        __import__(module_name)
        print(f"✅ {description}: {module_name}")
        return True
    except ImportError:
        print(f"❌ {description}: {module_name} - NOT AVAILABLE")
        return False

def main():
    """Main verification function"""
    print("=" * 60)
    print("  Cognitive Nexus AI - Packaging Setup Verification")
    print("=" * 60)
    print()
    
    # Check core files
    print("📁 Checking Core Files:")
    core_files = [
        ("cognitive_nexus_ai.py", "Main Streamlit App"),
        ("run.py", "Executable Wrapper"),
        ("cognitive_nexus_ai.spec", "PyInstaller Spec"),
        ("build_executable.bat", "Build Script"),
        ("launch_cognitive_nexus.bat", "Launcher Script"),
        ("icon.ico", "App Icon"),
        ("requirements_packaging.txt", "Packaging Requirements"),
        ("PACKAGING_INSTRUCTIONS.md", "Documentation"),
        ("QUICK_START.md", "Quick Start Guide")
    ]
    
    core_files_ok = True
    for filepath, description in core_files:
        if not check_file_exists(filepath, description):
            core_files_ok = False
    
    print()
    
    # Check Python dependencies
    print("🐍 Checking Python Dependencies:")
    python_deps = [
        ("streamlit", "Streamlit Framework"),
        ("requests", "HTTP Requests"),
        ("bs4", "BeautifulSoup"),
    ]
    
    python_deps_ok = True
    for module, description in python_deps:
        if not check_python_import(module, description):
            python_deps_ok = False
    
    # Check PyInstaller (optional)
    print()
    print("📦 Checking Packaging Tools:")
    pyinstaller_ok = check_python_import("PyInstaller", "PyInstaller")
    
    print()
    print("=" * 60)
    print("  VERIFICATION SUMMARY")
    print("=" * 60)
    
    if core_files_ok and python_deps_ok:
        print("✅ SETUP COMPLETE - Ready to build executable!")
        print()
        print("🚀 Next Steps:")
        print("1. Run: build_executable.bat")
        print("2. Test: launch_cognitive_nexus.bat")
        print("3. Distribute: dist/CognitiveNexusAI/ folder")
        
        if not pyinstaller_ok:
            print()
            print("ℹ️  Note: PyInstaller will be installed automatically during build")
        
    else:
        print("❌ SETUP INCOMPLETE - Please fix the issues above")
        
        if not core_files_ok:
            print("   - Missing core files")
        if not python_deps_ok:
            print("   - Missing Python dependencies")
            print("   - Run: pip install -r requirements_packaging.txt")
    
    print()
    print("=" * 60)

if __name__ == "__main__":
    main()
