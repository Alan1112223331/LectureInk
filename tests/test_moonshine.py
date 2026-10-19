"""Slow end-to-end check of basic mode with the real Moonshine model (skipped until it is downloaded)."""
import queue
import pytest
from audio import FileSource
from conftest import ASSETS, drain_events
from settings import Settings


def model_cached():
    try:
        from moonshine_voice.download import find_model_info, get_components_for_model_info
        from moonshine_voice.download_file import get_cache_dir
        from moonshine_voice import ModelArch
        info = find_model_info('en', ModelArch.MEDIUM_STREAMING)
        names = get_components_for_model_info(info)
        return any(p.name == names[0] for p in get_cache_dir().rglob('*'))
    except Exception:
        return False


@pytest.mark.skipif(not model_cached(), reason='Moonshine Medium Streaming 模型尚未下载')
def test_local_engine_transcribes_speech_sample():
    from engine_local import LocalEngine

    class Echo:
        def translate(self, text):
            return '译:' + text

    engine = LocalEngine(Settings(), translator=Echo())
    updates = []
    engine.update.connect(updates.append)
    engine.error.connect(lambda m: pytest.fail(m))
    audio = queue.Queue()
    source = FileSource(str(ASSETS / 'speech.wav'), audio, speed=4.0)
    source.start()
    engine._main(audio)
    drain_events()
    finals = [u['src'] for u in updates if u.get('closed')]
    text = ' '.join(finals).lower()
    assert 'synthetic speech sample' in text and 'personal information' in text
    assert any(u.get('tgt', '').startswith('译:') for u in updates)
