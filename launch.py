#!/usr/bin/env python3
"""
Cognitive Nexus AI Launcher
"""

import subprocess
import sys
import time
import webbrowser
import os
from pathlib import Path

def get_edge_path():
    """Get Microsoft Edge executable path"""
    edge_paths = [
        r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
        r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
        os.path.expanduser(r"~\AppData\Local\Microsoft\Edge\Application\msedge.exe"),
    ]
    for path in edge_paths:
        if os.path.exists(path):
            return path
    return None

def open_edge(url):
    """Open URL in Microsoft Edge"""
    edge_path = get_edge_path()
    if edge_path:
        try:
            subprocess.Popen([edge_path, url])
            return True
        except Exception as e:
            print(f"⚠️  Could not open Edge: {e}")
            # Fallback to default browser
            webbrowser.open(url)
            return False
    else:
        print("⚠️  Microsoft Edge not found, using default browser")
        webbrowser.open(url)
        return False

def main():
    print("🧠 Cognitive Nexus AI - Launcher")
    print("=" * 40)
    
    # Set environment variable to skip email prompt
    os.environ['STREAMLIT_BROWSER_GATHER_USAGE_STATS'] = 'false'
    
    print("🚀 Starting Streamlit app...")
    print("📱 The app will open in Microsoft Edge at http://localhost:8501")
    print("⏹️  Press Ctrl+C to stop the server")
    print("-" * 40)
    
    try:
        # Launch Streamlit
        process = subprocess.Popen([
            sys.executable, "-m", "streamlit", "run", 
            "cognitive_nexus_ai.py",
            "--server.port", "8501",
            "--server.address", "localhost",
            "--server.headless", "true",
            "--browser.gatherUsageStats", "false"
        ])
        
        # Wait for the server to start
        print("⏳ Waiting for server to start...")
        time.sleep(10)
        
        # Open browser in Microsoft Edge
        print("🌐 Opening Microsoft Edge...")
        open_edge("http://localhost:8501")
        
        # Wait for the process
        process.wait()
        
    except KeyboardInterrupt:
        print("\n\n👋 Stopping Cognitive Nexus AI...")
        process.terminate()
        return 0
    except Exception as e:
        print(f"❌ Error: {e}")
        return 1

if __name__ == "__main__":
    sys.exit(main())
