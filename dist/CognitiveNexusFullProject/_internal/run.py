#!/usr/bin/env python3
"""
Cognitive Nexus AI - Executable Wrapper
This script is used by PyInstaller to create a standalone executable.
It launches the Streamlit app exactly as if you ran 'streamlit run cognitive_nexus_ai.py'
"""

import sys
import os
import subprocess
import webbrowser
import time
from pathlib import Path
import threading

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
            print(f"WARNING: Could not open Edge: {e}")
            # Fallback to default browser
            webbrowser.open(url)
            return False
    else:
        print("WARNING: Microsoft Edge not found, using default browser")
        webbrowser.open(url)
        return False

def main():
    """Main entry point for the executable."""
    try:
        # Get the directory where the executable is located
        if getattr(sys, 'frozen', False):
            # Running as compiled executable
            base_path = Path(sys._MEIPASS)
            app_path = base_path / "cognitive_nexus_ai.py"
        else:
            # Running as script
            base_path = Path(__file__).parent
            app_path = base_path / "cognitive_nexus_ai.py"
        
        # Verify the main app file exists
        if not app_path.exists():
            print(f"ERROR: cognitive_nexus_ai.py not found at {app_path}")
            input("Press Enter to exit...")
            sys.exit(1)
        
        # Set the working directory to the app directory
        os.chdir(base_path)
        
        print("Starting Cognitive Nexus AI...")
        print("Opening in browser: http://localhost:8501")
        print("Press Ctrl+C to stop the application")
        print("-" * 50)

        # Open browser once after server startup delay.
        def delayed_browser_open():
            time.sleep(4)
            try:
                open_edge("http://localhost:8501")
            except Exception:
                pass

        threading.Thread(target=delayed_browser_open, daemon=True).start()

        # Run Streamlit in-process to avoid packaged EXE recursion.
        from streamlit.web import bootstrap
        os.environ["STREAMLIT_BROWSER_GATHER_USAGE_STATS"] = "false"
        bootstrap.run(
            str(app_path),
            False,
            [
                "--server.port=8501",
                "--server.address=localhost",
                "--server.headless=true",
                "--browser.gatherUsageStats=false",
            ],
            {},
        )
        
    except KeyboardInterrupt:
        print("\nShutting down Cognitive Nexus AI...")
        sys.exit(0)
    except Exception as e:
        print(f"ERROR starting Cognitive Nexus AI: {e}")
        print(f"Current directory: {os.getcwd()}")
        print(f"Looking for: {app_path}")
        input("Press Enter to exit...")
        sys.exit(1)

if __name__ == "__main__":
    main()
