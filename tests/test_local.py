import threading
import time
import pytest
import numpy as np
from engine_local import Agc, GlossaryTranslator, SentenceBuilder, clean_line, continue_sentence
from translator import RateLimited, TranslationWorker, parse_response, _split


class Recorder:
    def __init__(self):
        self.updates, self.finals, self.lives = [], [], []

    def builder(self):
        return SentenceBuilder(self.updates.append, lambda i, t: self.finals.append((i, t)),
                               lambda i, t: self.lives.append((i, t)))


def test_continue_sentence_lowercases_function_words_only():
    assert continue_sentence('the model', 'And the test set') == 'and the test set'
    assert continue_sentence('the model', 'Gaussian noise') == 'Gaussian noise'
    assert continue_sentence('Done.', 'And then') == 'And then'
    assert continue_sentence('the model', 'I think') == 'I think'


def test_clean_line_cuts_loops_and_drops_foreign_script():
    looped = 'And the, you know, the, the, the, the, the, the, the What?'
    assert clean_line(looped) == 'And the, you know, the, the… What?'
    assert clean_line('إِنَّا أَلَ') == ''
    assert clean_line('Very, very good.') == 'Very, very good.'
    assert clean_line('Use λ here') == 'Use λ here'


def test_agc_lifts_quiet_input_and_tames_loud_input():
    t = np.arange(1600) / 16000
    quiet = (0.004 * np.sin(2 * np.pi * 300 * t)).astype(np.float32)
    agc = Agc()
    for _ in range(200):
        out = agc(quiet)
    assert np.sqrt(np.mean(out ** 2)) > 0.03
    loud = Agc()
    for _ in range(20):
        out = loud(np.clip(quiet * 400, -1, 1))
    assert np.abs(out).max() < 0.5
    silent = Agc()
    noise = np.full(1600, 0.0005, dtype=np.float32)
    assert np.allclose(silent(noise), noise)


def test_rejected_noise_line_clears_its_draft():
    r = Recorder()
    b = r.builder()
    b.line(1, 'Real words', 0.0, 1.0, True)
    b.line(2, 'the, the', 1.2, 1.6, False)
    b.line(2, '', 1.2, 1.9, True)
    assert r.updates[-1] == {'id': 'u1', 'src': 'Real words', 'src_live': ''}
    b.line(3, 'continue here.', 2.0, 2.5, True)
    assert r.finals == [('u1', 'Real words continue here.')]


def test_lines_join_into_one_sentence_until_punctuation():
    r = Recorder()
    b = r.builder()
    b.line(1, 'The training set', 0.0, 1.0, False)
    b.line(1, 'The training set helps us', 0.0, 1.5, True)
    b.line(1, 'The training set helps us', 0.0, 1.5, True)   # Moonshine repeats completion events
    b.line(2, 'And the test set', 1.9, 2.8, False)
    assert r.updates[-1]['src'] == 'The training set helps us'
    assert r.updates[-1]['src_live'] == ' and the test set'
    b.line(2, 'And the test set generalizes.', 1.9, 3.2, True)
    assert r.finals == [('u1', 'The training set helps us and the test set generalizes.')]
    assert r.updates[-1]['closed'] is True


def test_long_silence_closes_an_unpunctuated_sentence():
    r = Recorder()
    b = r.builder()
    b.line(1, 'This problem is called overfitting', 0.0, 2.0, True)
    b.tick(2.5)
    assert r.finals == []
    b.tick(3.6)
    assert r.finals == [('u1', 'This problem is called overfitting')]


def test_gap_before_next_line_starts_a_new_sentence():
    r = Recorder()
    b = r.builder()
    b.line(1, 'First part', 0.0, 1.0, True)
    b.line(2, 'Second', 2.5, 3.0, False)
    assert r.finals == [('u1', 'First part')]
    assert r.updates[-1]['id'] == 'u2'


class FakeTranslator:
    def __init__(self, table=None, fail=0):
        self.table = table or {}
        self.calls = []
        self.fail = fail

    def translate(self, text):
        self.calls.append(text)
        if self.fail:
            self.fail -= 1
            raise RateLimited()
        return '\n'.join(self.table.get(line, '译:' + line) for line in text.split('\n'))


def test_glossary_replaces_default_rendering():
    fake = FakeTranslator({'overfitting': '过度拟合', 'This is overfitting.': '这是过度拟合。'})
    g = GlossaryTranslator(fake, 'overfitting = 过拟合\nlambda')
    assert g.translate('This is overfitting.') == '这是过拟合。'
    assert fake.calls[0] == 'overfitting'   # one batched lookup for all terms


def test_glossary_without_targets_makes_no_extra_requests():
    fake = FakeTranslator()
    assert GlossaryTranslator(fake, 'lambda\nKL divergence').translate('x') == '译:x'
    assert fake.calls == ['x']


def collect_worker(translator):
    results, done = [], threading.Event()

    def on_result(sid, text, final):
        results.append((sid, text, final))
    worker = TranslationWorker(translator, on_result)
    return worker, results


def test_worker_orders_finals_and_drops_superseded_drafts():
    fake = FakeTranslator()
    worker, results = collect_worker(fake)
    worker.LIVE_INTERVAL = 0
    worker.submit_live('a', 'draft one')
    worker.submit_live('a', 'draft two')
    worker.submit_final('a', 'final a')
    worker.submit_final('b', 'final b')
    worker.close()
    finals = [r for r in results if r[2]]
    assert finals == [('a', '译:final a', True), ('b', '译:final b', True)]
    assert ('a', '译:draft one', False) not in results


def test_worker_ignores_drafts_after_final():
    fake = FakeTranslator()
    worker, results = collect_worker(fake)
    worker.submit_final('a', 'final')
    worker.close()
    worker.submit_live('a', 'late draft')
    assert results == [('a', '译:final', True)]


def test_worker_retries_finals_after_rate_limit(monkeypatch):
    monkeypatch.setattr(time, 'sleep', lambda s: None)
    fake = FakeTranslator(fail=1)
    notices = []
    worker = TranslationWorker(fake, lambda *a: results.append(a), notices.append)
    results = []
    worker.submit_final('a', 'text')
    worker.close()
    assert results == [('a', '译:text', True)]
    assert notices and '限流' in notices[0]


def test_google_response_parsing_and_splitting():
    assert parse_response([[['你好', 'Hello'], ['世界', 'world'], [None, None]]]) == '你好世界'
    with pytest.raises(ValueError):
        parse_response(None)
    parts = _split('One. ' * 500, 1500)
    assert all(len(p) <= 1500 for p in parts) and ''.join(parts).replace(' ', '') == ('One.' * 500)
