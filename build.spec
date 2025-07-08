# -*- mode: python ; coding: utf-8 -*-

a = Analysis(
    ['main_app.py'],
    pathex=[],
    binaries=[],
    # [핵심] 여기에 포함할 모든 데이터 파일을 명확히 명시합니다.
    # ('소스 파일 이름', '실행 파일 내부의 목적지 폴더') 형식입니다.
    datas=[
        ('config.ini', '.'),
        ('serene-exchange-438319-r7-1dc9aac8b9cf.json', '.')
    ],
    hiddenimports=[],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=None,
    noarchive=False,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='TouristAnalyzer', # 최종 .exe 파일의 이름
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False, # GUI 앱이므로 콘솔 창을 숨깁니다.
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name='TouristAnalyzer',
)
