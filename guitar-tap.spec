# -*- mode: python ; coding: utf-8 -*-

import sys
import platform
added_binaries = []
if sys.platform == 'darwin':
    if platform.machine() == 'x86_64':
        added_binaries = [ ('/Users/dws/portaudio/lib/libportaudio.2.dylib', '.') ]
        
with open(os.path.abspath('./version'), 'r') as f:
    version = f.read().rstrip()
    f.close()

print(f'Creating build for version {version}')

block_cipher = None

added_files = [
    ('guitar-tap.ico', '.'),
    ('icons','icons'),
    ('version', '.')
    ]

a = Analysis(
    ['guitar_tap.py'],
    pathex=[],
    binaries=added_binaries,
    datas=added_files,
    hiddenimports=[],
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
    name='guitar-tap',
    icon='icons/guitar-tap.ico',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity='Developer ID Application: David Smith (43QHHT3XK2)',
    entitlements_file='entitlements.plist',
)
coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name='guitar-tap',
)

package_version=f'{version}.0'

app = BUNDLE(coll,
    name='Guitar Tap.app',
    icon='icons/guitar-tap.icns',
    version=package_version,
    bundle_identifier='com.dolcesfogato.guitar-tap',
    info_plist={
      'CFBundleName': 'Guitar Tap',
      'CFBundleDisplayName': 'Guitar Tap',
      'CFBundleVersion': package_version,
      'CFBundleShortVersionString': package_version,
      'NSPrincipalClass': 'NSApplication',
      'NSAppleScriptEnabled': False,
      'NSRequiresAquaSystemAppearance': 'No',
      'NSHighResolutionCapable': 'True',
      'NSMicrophoneUsageDescription': 'Guitar Tap from the audio inputs to show spectrum and peaks'
    },
)
