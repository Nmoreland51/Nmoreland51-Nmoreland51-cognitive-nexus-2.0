#!/usr/bin/env python3
"""
Automated changelog updater for Cognitive Nexus AI
"""

import os
from datetime import datetime
from version import VERSION_INFO, get_changelog_entry

def update_changelog():
    """Update CHANGELOG.md with current version info"""
    changelog_path = "CHANGELOG.md"
    
    # Create changelog if it doesn't exist
    if not os.path.exists(changelog_path):
        with open(changelog_path, 'w') as f:
            f.write("# Cognitive Nexus AI - Changelog\n\n")
    
    # Read existing changelog
    with open(changelog_path, 'r') as f:
        content = f.read()
    
    # Get new entry
    new_entry = get_changelog_entry()
    
    # Check if this version already exists
    version_marker = f"## Version {VERSION_INFO['version']}"
    if version_marker in content:
        print(f"Version {VERSION_INFO['version']} already exists in changelog")
        return False
    
    # Insert new entry after the header
    lines = content.split('\n')
    header_end = 2  # After "# Cognitive Nexus AI - Changelog\n\n"
    
    new_content = (
        '\n'.join(lines[:header_end]) + 
        new_entry + '\n' +
        '\n'.join(lines[header_end:])
    )
    
    # Write updated changelog
    with open(changelog_path, 'w') as f:
        f.write(new_content)
    
    print(f"✅ Changelog updated with version {VERSION_INFO['version']}")
    return True

def create_release_notes():
    """Create release notes file"""
    notes_path = f"release_notes_v{VERSION_INFO['version']}.md"
    
    with open(notes_path, 'w') as f:
        f.write(f"# Cognitive Nexus AI v{VERSION_INFO['version']} Release Notes\n\n")
        f.write(f"**Release Date:** {datetime.now().strftime('%Y-%m-%d')}\n\n")
        f.write(get_changelog_entry())
        f.write(f"\n## Installation\n\n")
        f.write("1. Download `CognitiveNexusAI.exe`\n")
        f.write("2. Run the executable\n")
        f.write("3. The app will start automatically in your browser\n\n")
        f.write("## Features\n\n")
        for feature in VERSION_INFO['features']:
            f.write(f"- {feature}\n")
    
    print(f"✅ Release notes created: {notes_path}")

if __name__ == "__main__":
    update_changelog()
    create_release_notes()
