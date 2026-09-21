# Third-party notices

LectureInk uses Python, PySide6 / Qt, Shiboken6, PyAudioWPatch / PortAudio, NumPy, requests and their runtime dependencies, plus ONNX Runtime and the Silero VAD model.

License texts supplied with the distribution are retained in `third_party/licenses/`. Python package versions are pinned in `requirements.txt`; this directory also includes ONNX Runtime's third-party notices.

## Qt and PySide6

Unmodified Qt / PySide6 / Shiboken6 components are distributed under LGPLv3 where applicable. The application sources and build configuration are provided so the application can be rebuilt using modified compatible libraries.

- https://code.qt.io/cgit/pyside/pyside-setup.git/
- https://code.qt.io/cgit/qt/qtbase.git/
- https://download.qt.io/official_releases/QtForPython/pyside6/

## Speech activity detection

- Silero VAD: https://github.com/snakers4/silero-vad (MIT).
- Exact model revision and hashes: `src/assets/silero-source.json`.
- Model license: `src/assets/Silero-LICENSE.txt`.
- ONNX Runtime: https://github.com/microsoft/onnxruntime (MIT; additional third-party notices included).

Other Python package source distributions are available through https://pypi.org/ at the versions specified in `requirements.txt`.
