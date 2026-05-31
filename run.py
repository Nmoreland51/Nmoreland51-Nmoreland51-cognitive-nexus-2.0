#!/usr/bin/env python3
"""
Cognitive Nexus - Launcher Script
Launches the Streamlit app with optional demo mode
"""

import sys
import os
import subprocess
import webbrowser
import time
import argparse
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
            webbrowser.open(url)
            return False
    else:
        print("WARNING: Microsoft Edge not found, using default browser")
        webbrowser.open(url)
        return False

def main():
    """Main entry point"""
    parser = argparse.ArgumentParser(description="Launch Cognitive Nexus")
    parser.add_argument("--demo", action="store_true", help="Enable demo mode with sample data")
    parser.add_argument("--port", type=int, default=8501, help="Port to run on (default: 8501)")
    args = parser.parse_args()

    try:
        # Get the directory where the script is located
        if getattr(sys, 'frozen', False):
            # Running as compiled executable
            base_path = Path(sys._MEIPASS)
            app_path = base_path / "app.py"
        else:
            # Running as script
            base_path = Path(__file__).parent
            app_path = base_path / "app.py"

        # Verify the main app file exists
        if not app_path.exists():
            print(f"ERROR: app.py not found at {app_path}")
            input("Press Enter to exit...")
            sys.exit(1)

        # Set the working directory to the app directory
        os.chdir(base_path)

        mode = "DEMO" if args.demo else "STANDARD"
        print(f"Starting Cognitive Nexus ({mode} mode)...")
        print(f"Opening in browser: http://localhost:{args.port}")
        print("Press Ctrl+C to stop the application")
        print("-" * 50)

        # Set demo environment variable if demo mode
        if args.demo:
            os.environ["COGNITIVE_NEXUS_DEMO"] = "1"

        # Open browser once after server startup delay
        def delayed_browser_open():
            time.sleep(4)
            try:
                open_edge(f"http://localhost:{args.port}")
            except Exception:
                pass

        threading.Thread(target=delayed_browser_open, daemon=True).start()

        # Run Streamlit
        from streamlit.web import bootstrap
        os.environ["STREAMLIT_BROWSER_GATHER_USAGE_STATS"] = "false"
        bootstrap.run(
            str(app_path),
            False,
            [
                f"--server.port={args.port}",
                "--server.address=localhost",
                "--server.headless=true",
                "--browser.gatherUsageStats=false",
            ],
            {},
        )

    except KeyboardInterrupt:
        print("\nShutting down Cognitive Nexus...")
        sys.exit(0)
    except Exception as e:
        print(f"ERROR starting Cognitive Nexus AI: {e}")
        print(f"Current directory: {os.getcwd()}")
        print(f"Looking for: {app_path}")
        input("Press Enter to exit...")
        sys.exit(1)

if __name__ == "__main__":
    main()
