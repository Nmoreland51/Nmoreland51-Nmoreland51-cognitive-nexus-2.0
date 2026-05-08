# -*- mode: python ; coding: utf-8 -*-
from PyInstaller.utils.hooks import collect_submodules

block_cipher = None

hiddenimports = collect_submodules('streamlit') + [
    'requests',
    'bs4',
    'trafilatura',
    'psutil',
    'sqlite3',
    'webbrowser',
    'threading',
    'subprocess',
]

datas = [
    ('cognitive_nexus_ai.py', '.'),
    ('run.py', '.'),
    ('version.py', '.'),
    ('requirements.txt', '.'),
    ('icon.ico', '.'),
    ('ai_system', 'ai_system'),
    ('data', 'data'),
    ('commands', 'commands'),
    ('skills', 'skills'),
    ('tests', 'tests'),
    ('cognitive_nexus', 'cognitive_nexus'),
    ('.agents', '.agents'),
    ('.codex-plugin', '.codex-plugin'),
    ('fullstack-local', 'fullstack-local'),
    ('generated_images', 'generated_images'),
]

a = Analysis(
    ['run.py'],
    pathex=[],
    binaries=[],
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='CognitiveNexusFullProject',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=True,
    disable_windowed_traceback=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon='icon.ico',
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name='CognitiveNexusFullProject'
)
