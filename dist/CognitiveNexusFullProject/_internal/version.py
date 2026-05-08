"""
Version management for Cognitive Nexus AI
"""

__version__ = "3.0.0"
__build__ = "2024.09.18"
__author__ = "Cognitive Nexus Team"

VERSION_INFO = {
    "version": __version__,
    "build": __build__,
    "author": __author__,
    "features": [
        "AI Chat Interface",
        "Image Generation with Stable Diffusion",
        "Persistent Memory & Knowledge",
        "Web Research & Scraping",
        "Multi-tab Interface",
        "Performance Monitoring"
    ]
}

def get_version_string():
    """Get formatted version string"""
    return f"v{__version__} (Build {__build__})"

def get_changelog_entry():
    """Get changelog entry for current version"""
    return f"""
## Version {__version__} - {__build__}

### ✨ New Features
- Unified application with all features
- Fast image generation (15-30 seconds)
- One-click dependency installation
- Persistent chat memory
- Enhanced web research

### 🔧 Improvements
- Optimized Stable Diffusion model (156MB)
- Dynamic dependency detection
- Streamlined user interface
- Better error handling

### 🐛 Bug Fixes
- Fixed progress bar hanging
- Resolved duplicate element IDs
- Improved installation flow
"""
