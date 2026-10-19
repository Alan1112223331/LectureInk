# -*- mode: python ; coding: utf-8 -*-
# Single-file Windows build. The Moonshine model is not bundled: it is downloaded on first use.
from pathlib import Path
import moonshine_voice

moonshine_dir = Path(moonshine_voice.__file__).parent

a = Analysis(
    ['src/app.py'],
    pathex=['src'],
    binaries=[(str(moonshine_dir / 'moonshine.dll'), 'moonshine_voice'),
              (str(moonshine_dir / 'onnxruntime.dll'), 'moonshine_voice')],
    datas=[],
    hiddenimports=['moonshine_voice.transcriber', 'moonshine_voice.download', 'websocket'],
    excludes=['moonshine_voice.tts', 'moonshine_voice.lora', 'moonshine_voice.agent_flow', 'moonshine_voice.mic_transcriber',
              'sounddevice', 'torch', 'transformers', 'scipy', 'tkinter', 'onnxruntime', 'PySide6.QtNetwork',
              'PySide6.QtQml', 'PySide6.QtQuick', 'PySide6.QtOpenGL', 'PySide6.QtSvg', 'PySide6.QtPdf'],
    noarchive=False,
)
# Windows ships a compatible ICU; Qt's optional ICU DLLs only add size.
a.binaries = [b for b in a.binaries if not Path(b[0]).name.lower().startswith(('icudt', 'icuin', 'icuuc'))]
pyz = PYZ(a.pure)
exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name='LectureInk',
    console=False,
    upx=False,
    icon=None,
)
