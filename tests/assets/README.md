# Synthetic speech fixtures

Both files were generated with the Windows speech synthesizer (System.Speech) from fixed text written for testing. Neither is a microphone recording, a real lecture, or anyone's voice.

**speech.wav** (8 s, 22.05 kHz):

> This is a synthetic speech sample for testing voice activity detection. There is no personal information in this recording.

**lecture.wav** (50 s, 16 kHz). Seven short lecture-style sentences about overfitting and ridge regression. It has 3.2-second pauses after the second and fifth sentences, so it exercises paragraph breaks.

The fast tests do not need these files. The slow local-engine test, and demos run with `--audio-file`, play them at real-time speed.
