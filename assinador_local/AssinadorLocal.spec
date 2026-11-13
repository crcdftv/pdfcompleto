# -*- mode: python ; coding: utf-8 -*-


a = Analysis(
    ['assinador_local.py'],
    pathex=[],
    binaries=[('C:\\\\Windows\\\\System32\\\\aetpkss1.dll', '.')],
    datas=[],
    hiddenimports=['PyKCS11', 'pyhanko.sign.pkcs11', 'pyhanko.sign.signers', 'pyhanko.sign.fields', 'pyhanko.stamp', 'pyhanko.sign.general'],
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
    a.binaries,
    a.datas,
    [],
    name='AssinadorLocal',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=True,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
