#!/usr/bin/env python3
"""
Cognitive Nexus AI - Launcher Script
====================================
Simple launcher script for the Cognitive Nexus AI application.
This script handles environment setup and launches the Streamlit app.
"""

import subprocess
import sys
import os
from pathlib import Path

def check_dependencies():
    """Check if required dependencies are installed."""
    required_packages = ['streamlit', 'requests', 'beautifulsoup4']
    missing_packages = []
    
    for package in required_packages:
        try:
            __import__(package)
        except ImportError:
            missing_packages.append(package)
    
    if missing_packages:
        print("❌ Missing required packages:")
        for package in missing_packages:
            print(f"   - {package}")
        print("\n💡 Install them with:")
        print(f"   pip install {' '.join(missing_packages)}")
        print("\n   Or install all dependencies with:")
        print("   pip install -r requirements.txt")
        return False
    
    return True

def check_ollama():
    """Check if Ollama is available."""
    try:
        result = subprocess.run(['ollama', 'list'], capture_output=True, text=True, timeout=5)
        if result.returncode == 0:
            models = result.stdout.strip().split('\n')[1:]  # Skip header
            if models and models[0].strip():
                print("✅ Ollama detected with models:")
                for model in models[:3]:  # Show first 3 models
                    if model.strip():
                        print(f"   - {model.split()[0]}")
                if len(models) > 3:
                    print(f"   ... and {len(models) - 3} more")
                return True
            else:
                print("⚠️  Ollama detected but no models installed")
                print("   Install a model with: ollama pull llama2")
                return False
    except (subprocess.TimeoutExpired, subprocess.CalledProcessError, FileNotFoundError):
        print("ℹ️  Ollama not detected")
        print("   Install from: https://ollama.ai/")
        return False

def main():
    """Main launcher function."""
    print("🧠 Cognitive Nexus AI Launcher")
    print("=" * 40)
    
    # Check if the main file exists
    main_file = Path(__file__).parent / "cognitive_nexus_ai.py"
    if not main_file.exists():
        print(f"❌ Main application file not found: {main_file}")
        print("   Please ensure cognitive_nexus_ai.py is in the same directory")
        return 1
    
    # Check dependencies
    print("\n🔍 Checking dependencies...")
    if not check_dependencies():
        return 1
    
    # Check Ollama (optional)
    print("\n🤖 Checking Ollama...")
    check_ollama()
    
    # Launch the application
    print("\n🚀 Launching Cognitive Nexus AI...")
    print("   The app will open in your default browser")
    print("   Press Ctrl+C to stop the server")
    print("-" * 40)
    
    try:
        # Launch Streamlit
        subprocess.run([
            sys.executable, "-m", "streamlit", "run", 
            str(main_file),
            "--server.port", "8501",
            "--server.address", "localhost"
        ])
    except KeyboardInterrupt:
        print("\n\n👋 Cognitive Nexus AI stopped")
        return 0
    except Exception as e:
        print(f"\n❌ Error launching application: {e}")
        return 1

if __name__ == "__main__":
    sys.exit(main())
