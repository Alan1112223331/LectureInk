from transcript import LINE_BREAK, Transcript


def make(*updates, src='en', tgt='zh'):
    t = Transcript(src, tgt)
    for u in updates:
        t.apply(u)
    return t


def test_segments_flow_into_one_paragraph_until_a_long_pause():
    t = make({'id': 'a', 'src': 'First sentence.', 'tgt': '第一句。', 'start': 0.0, 'end': 2.0},
             {'id': 'b', 'src': 'Second one.', 'tgt': '第二句。', 'start': 2.6, 'end': 4.0},
             {'id': 'c', 'src': 'After a pause.', 'tgt': '停顿之后。', 'start': 7.0, 'end': 8.0})
    assert len(t.paragraphs) == 2
    assert t.text(0, 'src') == 'First sentence. Second one.'
    assert t.text(0, 'tgt') == '第一句。第二句。'
    assert t.text(1, 'src') == 'After a pause.'


def test_long_paragraph_breaks_at_next_segment():
    t = Transcript()
    t.apply({'id': 'a', 'src': 'x' * (Transcript.PARA_CHARS + 5), 'start': 0, 'end': 1})
    t.apply({'id': 'b', 'src': 'next', 'start': 1.1, 'end': 2})
    assert len(t.paragraphs) == 2


def test_live_text_is_a_separate_run_and_is_replaced():
    t = make({'id': 'a', 'src': 'Hello', 'src_live': ' wor', 'start': 0})
    assert t.runs(0, 'src') == [('Hello', False), (' wor', True)]
    t.apply({'id': 'a', 'src': 'Hello world.', 'src_live': ''})
    assert t.runs(0, 'src') == [('Hello world.', False)]


def test_cjk_segments_without_punctuation_get_a_comma():
    t = make({'id': 'a', 'tgt': '今天我们讨论模型', 'start': 0, 'end': 1},
             {'id': 'b', 'tgt': '它如何学习。', 'start': 1.2, 'end': 2},
             {'id': 'c', 'tgt': '然后', 'tgt_live': '继续', 'start': 2.2, 'end': 3})
    assert t.text(0, 'tgt') == '今天我们讨论模型，它如何学习。然后继续'


def test_stray_spaces_in_chinese_are_removed_but_latin_spacing_kept():
    t = make({'id': 'a', 'tgt': '输出。 这并不能', 'tgt_live': ' 改变 电路', 'start': 0},
             {'id': 'b', 'tgt': '两个 C 之间。 Okay', 'start': 1, 'end': 2})
    assert t.runs(0, 'tgt') == [('输出。这并不能', False), ('改变电路', True), ('，两个 C 之间。Okay', False)]
    assert make({'id': 'a', 'src': 'Keep  this', 'start': 0}).text(0, 'src') == 'Keep  this'


def test_whitespace_at_segment_edges_is_trimmed():
    t = make({'id': 'a', 'src': ' Tokens with', 'src_live': ' spaces ', 'start': 0})
    assert t.runs(0, 'src') == [('Tokens with', False), (' spaces', True)]


def test_dirty_tracks_earliest_changed_paragraph():
    t = make({'id': 'a', 'src': 'One.', 'start': 0, 'end': 1}, {'id': 'b', 'src': 'Two.', 'start': 5, 'end': 6})
    assert t.take_dirty() == 0
    assert t.take_dirty() is None
    t.apply({'id': 'b', 'tgt': '二。'})
    assert t.take_dirty() == 1


def test_recent_runs_uses_whole_paragraphs():
    t = make({'id': 'a', 'tgt': '一。', 'start': 0, 'end': 1}, {'id': 'b', 'tgt': '二。', 'start': 5, 'end': 6},
             {'id': 'c', 'tgt': '三', 'tgt_live': '中', 'start': 10, 'end': 11})
    assert t.recent_runs('tgt') == [('二。' + LINE_BREAK + '三', False), ('中', True)]
    assert t.recent_runs('tgt', paragraphs=1) == [('三', False), ('中', True)]


def test_round_trip_folds_live_text_into_final():
    t = make({'id': 'a', 'src': 'Done.', 'tgt': '完成。', 'start': 0, 'end': 1},
             {'id': 'b', 'src': 'Half', 'src_live': ' way', 'start': 9, 'end': 10})
    loaded = Transcript.from_dict(t.to_dict())
    assert loaded.pairs() == [('Done.', '完成。'), ('Half way', '')]
    assert loaded.runs(1, 'src') == [('Half way', False)]


def test_export_formats():
    t = make({'id': 'a', 'src': 'A <b> c.', 'tgt': '甲。', 'start': 0, 'end': 1})
    html = t.export('html', '课堂文稿', 'ML')
    assert '&lt;b&gt;' in html and '甲。' in html
    md = t.export('md', '课堂文稿')
    assert md.startswith('# 课堂文稿') and '> A <b> c.' in md
    assert 'A <b> c.' not in t.export('txt', '课堂文稿', which='target')
