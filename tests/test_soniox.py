import json
import queue
import numpy as np
import websocket
from engine_soniox import SonioxAssembler, SonioxEngine, build_config
from conftest import drain_events
from settings import Settings


def tok(text, final=True, status='original', start=None, end=None):
    t = {'text': text, 'is_final': final, 'translation_status': status}
    if start is not None:
        t['start_ms'], t['end_ms'] = start, end if end is not None else start + 200
    return t


def test_config_maps_topic_and_glossary_to_context():
    s = Settings(topic='Machine learning', glossary='overfitting = 过拟合\nlambda', source_language='en')
    config = build_config(s, 'key')
    assert config['translation'] == {'type': 'one_way', 'target_language': 'zh'}
    assert config['language_hints'] == ['en']
    assert config['context']['terms'] == ['overfitting', 'lambda']
    assert config['context']['translation_terms'] == [{'source': 'overfitting', 'target': '过拟合'}]
    assert 'language_hints' not in build_config(Settings(source_language='auto'), 'key')
    assert 'context' not in build_config(Settings(), 'key')


def test_final_tokens_append_and_live_tokens_are_replaced():
    a = SonioxAssembler()
    a.feed({'tokens': [tok('Hello', start=0), tok(' wor', False, start=300)]})
    seg = a.segments[0]
    assert (seg['src'], seg['src_live']) == ('Hello', ' wor')
    a.feed({'tokens': [tok(' world', False, start=300)]})
    assert (seg['src'], seg['src_live']) == ('Hello', ' world')
    a.feed({'tokens': [tok(' world', start=300, end=600), tok('.', start=600, end=650)]})
    assert (seg['src'], seg['src_live'], seg['end']) == ('Hello world.', '', 0.65)


def test_end_token_closes_utterance_and_translation_follows():
    a = SonioxAssembler()
    a.feed({'tokens': [tok('Hello', start=0), tok(' there.', start=200), tok('你好', False, 'translation')]})
    assert a.segments[0]['tgt_live'] == '你好'
    updates = a.feed({'tokens': [tok('<end>'), tok('你好。', True, 'translation')]})
    assert a.segments[0]['closed'] and a.segments[0]['tgt'] == '你好。' and a.segments[0]['tgt_live'] == ''
    assert updates[0]['id'] == 's0'
    # Next utterance: its translation must go to the new segment, not the old one.
    a.feed({'tokens': [tok('Next', start=3000), tok(' one.', start=3200), tok('<end>')]})
    a.feed({'tokens': [tok('下一个。', True, 'translation')]})
    assert a.segments[0]['tgt'] == '你好。'
    assert a.segments[1]['tgt'] == '下一个。'


def test_translation_waits_for_lagging_utterance():
    a = SonioxAssembler()
    a.feed({'tokens': [tok('A fairly long first sentence here.', start=0), tok('<end>')]})
    a.feed({'tokens': [tok('Second.', start=2000), tok('第一', True, 'translation')]})
    # 2 Chinese chars for a 34-char sentence is not yet a plausible translation; keep filling segment 0.
    a.feed({'tokens': [tok('句话很长。', True, 'translation')]})
    assert a.segments[0]['tgt'] == '第一句话很长。'
    assert a.segments[1]['tgt'] == ''


def test_untranslated_target_language_speech_is_mirrored():
    a = SonioxAssembler()
    a.feed({'tokens': [tok('同学们好', True, 'none', start=0)]})
    assert a.segments[0]['src'] == a.segments[0]['tgt'] == '同学们好'


class FakeSocket:
    def __init__(self, messages):
        self.messages = queue.Queue()
        for m in messages:
            self.messages.put(json.dumps(m))
        self.sent, self.binary, self.closed = [], [], False

    def send(self, data):
        self.sent.append(data)
        if data == '':
            self.messages.put(json.dumps({'tokens': [], 'finished': True}))

    def send_binary(self, data):
        self.binary.append(data)

    def recv(self):
        try:
            return self.messages.get_nowait()
        except queue.Empty:
            raise websocket.WebSocketTimeoutException('no reply yet') from None

    def settimeout(self, seconds):
        self.timeout = seconds

    def close(self):
        self.closed = True


def run_engine(messages, chunks=3):
    ws = FakeSocket(messages)
    engine = SonioxEngine(Settings(), 'secret', connect=lambda: ws)
    updates, errors = [], []
    engine.update.connect(updates.append)
    engine.error.connect(errors.append)
    audio = queue.Queue()
    for _ in range(chunks):
        audio.put(np.zeros(1600, dtype=np.float32))
    audio.put(None)
    engine._main(audio)
    drain_events()
    return ws, updates, errors


def test_engine_streams_audio_and_finishes():
    ws, updates, errors = run_engine([{'tokens': [tok('Hi', start=0), tok('嗨', True, 'translation')]}])
    assert errors == []
    config = json.loads(ws.sent[0])
    assert config['audio_format'] == 'pcm_s16le' and config['sample_rate'] == 16000
    assert len(ws.binary) == 3 and all(len(b) == 3200 for b in ws.binary)
    assert ws.sent[-1] == '' and ws.closed
    assert updates[-1]['src'] == 'Hi' and updates[-1]['tgt'] == '嗨'


def test_key_shape_check_rejects_pasted_text():
    from settings import looks_like_api_key
    assert looks_like_api_key('a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6')
    assert not looks_like_api_key('this is a sentence that was pasted by mistake')
    assert not looks_like_api_key('密钥' * 10)
    assert not looks_like_api_key('short')


def test_silent_disconnect_before_results_points_to_the_key():
    class Dropping(FakeSocket):
        def recv(self):
            raise ConnectionError('closed')
    ws = Dropping([])
    engine = SonioxEngine(Settings(), 'secret', connect=lambda: ws)
    errors = []
    engine.error.connect(errors.append)
    audio = queue.Queue()
    audio.put(np.zeros(1600, dtype=np.float32))
    audio.put(None)
    engine._main(audio)
    drain_events()
    assert errors and 'API Key' in errors[0]


def test_engine_sends_and_reads_from_one_thread():
    import threading

    class OneThread(FakeSocket):
        def _check(self):
            owner = getattr(self, 'owner', None) or threading.get_ident()
            self.owner = owner
            assert threading.get_ident() == owner, 'socket used from two threads'

        def send(self, data):
            self._check()
            super().send(data)

        def send_binary(self, data):
            self._check()
            super().send_binary(data)

        def recv(self):
            self._check()
            return super().recv()
    ws = OneThread([{'tokens': [tok('Hi', start=0)]}])
    engine = SonioxEngine(Settings(), 'secret', connect=lambda: ws)
    errors = []
    engine.error.connect(errors.append)
    audio = queue.Queue()
    for _ in range(5):
        audio.put(np.zeros(1600, dtype=np.float32))
    audio.put(None)
    engine._main(audio)
    drain_events()
    assert errors == [] and len(ws.binary) == 5


def test_engine_reports_service_errors_in_chinese():
    _, _, errors = run_engine([{'tokens': [], 'error_code': 401, 'error_message': 'bad key'}])
    assert errors == ['Soniox API Key 无效。']
