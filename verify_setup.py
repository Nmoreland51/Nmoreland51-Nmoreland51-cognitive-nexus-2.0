#!/usr/bin/env python3
"""
Setup verification script for Cognitive Nexus
Checks if all required components are properly configured
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

def check_ollama_connection():
    """Check if Ollama is running and has models"""
    try:
        import requests
        response = requests.get("http://localhost:11434/api/tags", timeout=5)
        if response.status_code == 200:
            models = response.json().get("models", [])
            if models:
                print(f"✅ Ollama available with {len(models)} models")
                return True
            else:
                print("⚠️  Ollama running but no models installed")
                return False
        else:
            print("❌ Ollama API error")
            return False
    except:
        print("❌ Ollama not accessible (start Ollama first)")
        return False

def main():
    """Main verification function"""
    print("=" * 60)
    print("  Cognitive Nexus - Setup Verification")
    print("=" * 60)
    print()

    # Check core files
    print("📁 Checking Core Files:")
    core_files = [
        ("app.py", "Main Streamlit Application"),
        ("modules/nexus_core.py", "Core Orchestration Module"),
        ("modules/reality_research_agent.py", "Research Agent"),
        ("search/bloodhound_search.py", "Web Search Engine"),
        ("core/reality_grounding/", "Fact Verification Module"),
        ("requirements.txt", "Python Dependencies"),
        ("README.md", "Documentation"),
        ("QUICK_START.md", "Quick Start Guide"),
        ("PROJECT_STRUCTURE.md", "Project Structure"),
        ("AGENTS.md", "AI Agents Documentation")
    ]

    core_files_ok = True
    for filepath, description in core_files:
        if not check_file_exists(filepath, description):
            core_files_ok = False

    print()

    # Check Python dependencies
    print("🐍 Checking Python Dependencies:")
    python_deps = [
        ("streamlit", "Web UI Framework"),
        ("requests", "HTTP Client"),
        ("beautifulsoup4", "HTML Parsing"),
        ("newspaper3k", "Article Extraction"),
        ("dataclasses_json", "Data Serialization"),
        ("pathlib", "Path Utilities"),
    ]

    python_deps_ok = True
    for module, description in python_deps:
        if not check_python_import(module, description):
            python_deps_ok = False

    print()

    # Check Ollama
    print("🤖 Checking AI Providers:")
    ollama_ok = check_ollama_connection()

    print()

    # Check optional components
    print("🔧 Checking Optional Components:")
    optional_ok = True

    # ComfyUI check
    try:
        import requests
        response = requests.get("http://127.0.0.1:8188/", timeout=3)
        if response.status_code == 200:
            print("✅ ComfyUI available for image generation")
        else:
            print("⚠️  ComfyUI not responding")
            optional_ok = False
    except:
        print("⚠️  ComfyUI not available (image generation disabled)")
        optional_ok = False

    print()
    print("=" * 60)
    print("  VERIFICATION SUMMARY")
    print("=" * 60)

    if core_files_ok and python_deps_ok:
        print("✅ BASIC SETUP COMPLETE")
        print()
        print("🚀 Launch Options:")
        print("1. Web UI: python app.py")
        print("2. Launcher: launch.bat")
        print("3. Demo: python run.py --demo")

        if ollama_ok:
            print("✅ AI models ready")
        else:
            print("⚠️  Start Ollama for full functionality")

        if optional_ok:
            print("✅ All optional features available")
        else:
            print("ℹ️  Some optional features unavailable")

    else:
        print("❌ SETUP INCOMPLETE")
        if not core_files_ok:
            print("   - Missing core files")
        if not python_deps_ok:
            print("   - Missing Python dependencies")
            print("   - Run: pip install -r requirements.txt")

    print()
    print("📖 See QUICK_START.md for detailed setup instructions")
    
    print()
    print("=" * 60)

if __name__ == "__main__":
    main()
