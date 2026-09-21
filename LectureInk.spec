# -*- mode: python ; coding: utf-8 -*-
from pathlib import Path
from PyInstaller.utils.hooks import collect_all

datas, binaries, hiddenimports = collect_all('pyaudiowpatch')
datas += [(str(Path('src/assets')/name),'assets') for name in ('silero_vad.onnx','Silero-LICENSE.txt','silero-source.json')]
a = Analysis(['src/app.py'], pathex=[], binaries=binaries, datas=datas,
    hiddenimports=hiddenimports, hookspath=[], hooksconfig={}, runtime_hooks=[],
    excludes=[], noarchive=False, optimize=0)
# Qt uses Windows' ICU ABI with unsuffixed symbols. A developer PATH containing
# Git's ICU can make PyInstaller bundle an incompatible icuuc.dll (e.g. *_78).
# Windows 10 1903+ / Windows 11 provide the required ICU API as an OS component.
# Do not ship or shadow that system DLL with another application's copy.
a.binaries = [item for item in a.binaries
    if not Path(item[0]).name.lower().startswith(('icuuc', 'icudt', 'icuin'))]
pyz = PYZ(a.pure)
exe = EXE(pyz, a.scripts, a.binaries, a.datas, [], name='LectureInk',
    debug=False, bootloader_ignore_signals=False, strip=False, upx=False,
    runtime_tmpdir=None, console=False, disable_windowed_traceback=False)
