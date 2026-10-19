# Third-party notices

Licences below are as declared in each package's metadata. The Windows release zip contains the full licence texts in its `第三方许可` folder (one sub-folder per package, plus the GPL/LGPL, Python and ONNX Runtime texts).

| Component | Use | Licence |
| --- | --- | --- |
| [Moonshine Voice](https://github.com/moonshine-ai/moonshine) (`moonshine-voice` 0.1.5) | Local speech recognition runtime | MIT |
| Moonshine Medium Streaming English model | Downloaded on first use from download.moonshine.ai, not bundled | MIT (English models; non-English models use the Moonshine Community License and are not used here) |
| ONNX Runtime (bundled inside `moonshine-voice`) | Inference | MIT |
| [Qt for Python](https://www.qt.io/qt-for-python) (`PySide6_Essentials` 6.11.2) | User interface | LGPL-3.0-only (also GPL-2.0/GPL-3.0) |
| [PyAudioWPatch](https://github.com/s0d3s/PyAudioWPatch) 0.2.12.8, including PortAudio | WASAPI capture and loopback | Apache-2.0 (PortAudio: MIT) |
| NumPy 2.5.3 | Audio processing | BSD-3-Clause and others |
| Requests 2.34.2 (with urllib3, idna, charset-normalizer, certifi) | HTTP | Apache-2.0 (dependencies: MIT, BSD-3-Clause, MIT, MPL-2.0) |
| websocket-client 1.9.2 | Soniox WebSocket | Apache-2.0 |
| platformdirs, filelock, tqdm, google-crc32c | Dependencies of `moonshine-voice` | MIT, MIT, MPL-2.0 AND MIT, Apache-2.0 |
| CPython 3.13 (in the packaged EXE) | Runtime | PSF-2.0 |

Online services (not bundled): Soniox real-time API (API mode, user's own key) and Google Translate's public web endpoint (basic mode). Use of either is subject to that provider's terms.
