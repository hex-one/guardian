# -*- mode: python ; coding: utf-8 -*-
#
# Builds Guardian into a Windows executable:
#   pyinstaller Guardian.spec
# Output lands in dist/Guardian/ (the exe plus its supporting files).
# The forge that turns source into something someone else can just run.
#
# --- Antivirus / Windows Defender false positives ---
# Unsigned PyInstaller executables get flagged fairly often - a known,
# common issue, not specific to this app. Two real mitigations applied
# below (upx=False, exclude_binaries/COLLECT for a onedir layout) - same
# approach as the Ascended STT sibling project, same family, same care.
# See README.md's "Windows Defender / antivirus flagging" section for
# the full picture, including what these can and can't fix on their own.

a = Analysis(
    ['main.py'],
    pathex=[],
    binaries=[],
    datas=[
        ('ascended_logo.png', '.'),
        ('ascended_logo.ico', '.'),
        ('combo_arrow.png', '.'),
        ('style.qss', '.'),
        # Stamps which content version this build shipped with -- the
        # in-app updater (app_updater.py) compares this against
        # GitHub's copy to decide whether style.qss/the logo files
        # need refreshing. Needs to travel with the exe the same way
        # those do.
        ('content_version.txt', '.'),
    ],
    hiddenimports=[],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='Guardian',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    # UPX-compressed executables are frequently flagged by AV heuristics,
    # since UPX is heavily used by actual malware packers too, not just
    # legitimate small utilities. Leaving this off is a real, free
    # mitigation - the trade-off is a larger file size.
    upx=False,
    console=False,
    icon='ascended_logo.ico',
)

# onedir (a folder with the exe + supporting files) rather than onefile
# (a single exe that self-extracts to a temp folder at runtime) - onefile's
# runtime self-extraction is a behavioral pattern that heuristic AV engines
# often flag on its own, on top of everything else. Arrive as you are,
# nothing hidden in a temp folder.
coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name='Guardian',
)
