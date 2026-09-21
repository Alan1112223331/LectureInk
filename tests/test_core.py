import base64
import io
import json
import sys
from pathlib import Path
import wave
import threading
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src'))
import pytest
from core import parse_response,parse_preview,merge_segments,wav_bytes,AudioClient,Settings,transcript_text,protect_secret

def entry(source,zh='译文',**kwargs):return dict(source=source,zh=zh,uncertain=False,**kwargs)

def test_parse_fenced_and_refuse_missing_translation():
    assert parse_response('```json\n{"segments":[{"source":"Not always.","zh":"并非总是。"}]}\n```')['segments'][0]['zh']=='并非总是。'
    with pytest.raises(ValueError):parse_response('{"segments":[{"source":"test"}]}')
    with pytest.raises(ValueError):parse_response('{"segments":[')

def test_boundary_dedupe_does_not_erase_new_repetition():
    old=[entry('The matrix is singular.')]
    new={'segments':[entry('The matrix is singular.'),entry('Why?'),entry('Why?')]}
    merged,_=merge_segments(old,new,18,36)
    assert [e['source'] for e in merged]==['The matrix is singular.','Why?','Why?']

def test_incomplete_sentence_repaired_without_adding_duplicate():
    old=[entry('If lambda increases',pending=True)]
    new={'replace_last':entry('If lambda increases, the coefficients shrink.','若 λ 增大，系数会收缩。'),'segments':[entry('This is regularization.')],'incomplete_tail':False}
    merged,pending=merge_segments(old,new,18,36)
    assert len(merged)==2 and not pending
    assert merged[0]['source'].endswith('shrink.')

def test_unrelated_replacement_is_rejected():
    old=[entry('If lambda increases',pending=True)]
    merged,_=merge_segments(old,{'replace_last':entry('Bananas are yellow.'),'segments':[]},18,36)
    assert merged[0]['source']=='If lambda increases'

def test_wav_header_and_samples():
    raw=b'\x00\x00\xff\x7f'*16000
    with wave.open(io.BytesIO(wav_bytes(raw,16000)),'rb') as f:
        assert f.getnchannels()==1 and f.getsampwidth()==2 and f.getnframes()==32000
        assert f.readframes(32000)==raw

def test_context_payload_and_secret_not_in_text(monkeypatch):
    captured={}
    class Response:
        status_code=200;ok=True
        def json(self):return {'choices':[{'message':{'content':'{"segments":[]}'},'finish_reason':'stop'}]}
    def post(url,**kw):captured.update(kw);return Response()
    client=AudioClient('test-secret');monkeypatch.setattr(client.session,'post',post)
    client.translate(b'RIFF',Settings(topic='线性回归',glossary='ridge=岭回归'),[entry('Not invertible.','不可逆。')],5,23,False,threading.Event())
    body=captured['json'];assert body['model']=='Qwen/Qwen3-Omni-30B-A3B-Instruct'
    text=body['messages'][1]['content'][1]['text'];assert '线性回归' in text and '不可逆' in text and 'Not invertible' in text
    assert 'test-secret' not in json.dumps(body)
    assert body['messages'][1]['content'][0]['audio_url']['url'].startswith('data:audio/wav;base64,')

def test_dpapi_roundtrip():
    encrypted=protect_secret('temporary-test-key')
    assert 'temporary-test-key' not in encrypted
    assert protect_secret(encrypted,True)=='temporary-test-key'

def test_chinese_export_hides_source():
    txt=transcript_text([entry('source sentence','中文译文')],False)
    assert '中文译文' in txt and 'source sentence' not in txt

def test_fragment_completed_in_next_window_replaces_old_line():
    old=[entry('Alright, this lecture will focus on.',pending=True)]
    new={'segments':[entry('Alright, this lecture will focus on analytic regression.','本课重点讲解解析回归。'),entry('Now let us begin.')]}
    merged,_=merge_segments(old,new,18,36)
    assert len(merged)==2 and merged[0]['zh']=='本课重点讲解解析回归。'

def test_nearly_same_overlap_with_same_translation_is_updated():
    old=[entry('So we only talk about learning first.','所以我们先只讨论学习。')]
    new={'segments':[entry('So we only talk about learning first in this.','所以我们先只讨论学习。')]}
    merged,_=merge_segments(old,new,36,54)
    assert len(merged)==1 and merged[0]['source'].endswith('in this.')

def test_negation_difference_is_not_deduplicated():
    old=[entry('This will improve the accuracy.','这会提高准确率。')]
    new={'segments':[entry('This will not improve the accuracy.','这不会提高准确率。')]}
    merged,_=merge_segments(old,new,18,36)
    assert len(merged)==2

def test_provisional_misheard_word_is_corrected_from_overlap():
    old=[entry('So regularization is to suppress the sum.','所以正则化是为了抑制总和。',provisional=True)]
    result={'replace_last':entry('So regularization is to suppress the size of the parameter when learning.','正则化是为了在学习时抑制参数的大小。'),'segments':[entry('Now look at the coefficients.')]}
    merged,_=merge_segments(old,result,36,54)
    assert '总和' not in merged[0]['zh'] and '参数的大小' in merged[0]['zh']
    assert not merged[0]['provisional']


def test_stream_preview_waits_for_complete_pairs_and_never_inserts_token_lines():
    first={'source':'If lambda increases,\nthe coefficients shrink.','zh':'若 λ 增大，\n系数会收缩。'}
    value=json.dumps({'speech_present':True,'segments':[first,entry('This does not guarantee accuracy.','这不能保证准确性。')]},ensure_ascii=False)
    previews=[]
    class Response:
        def iter_lines(self,**kwargs):
            for i in range(0,len(value),3):yield 'data: '+json.dumps({'choices':[{'delta':{'content':value[i:i+3]}}]})
            yield 'data: '+json.dumps({'choices':[{'delta':{},'finish_reason':'stop'}]})
            yield 'data: [DONE]'
    obj,_=AudioClient('test')._read_stream(Response(),threading.Event(),previews.append,0)
    assert [len(x) for x in previews]==[1,2]
    assert all('\n' not in pair['source'] and '\n' not in pair['zh'] for p in previews for pair in p)
    assert parse_response(obj['choices'][0]['message']['content'])['segments'][0]['source'].endswith('shrink.')


def test_no_speech_claim_discards_inconsistent_generated_words():
    text=json.dumps({'speech_present':False,'segments':[entry('Invented text.')],'replace_last':entry('Wrong correction.')})
    assert parse_preview(text)==[]
    parsed=parse_response(text)
    assert not parsed['segments'] and 'replace_last' not in parsed


def test_broken_sse_is_never_a_committed_response():
    class Response:
        def iter_lines(self,**kwargs):
            yield 'data: '+json.dumps({'choices':[{'delta':{'content':'{"segments":[]}'}}]})
    with pytest.raises(ValueError,match='中断'):
        AudioClient('test')._read_stream(Response(),threading.Event(),lambda value:None,0)


def test_multi_sentence_boundary_correction_keeps_next_sentence_provisional():
    old=[entry('Increasing lambda from',pending=True)]
    raw={'replace_last':entry('Increasing lambda from 0.01 to 0.1 strengthens regularization. A lower error does not guarantee accuracy.',
                              '将 λ 从0.01增到0.1会加强正则化。较低的误差并不能保证准确性。'),'segments':[]}
    parsed=parse_response(json.dumps(raw,ensure_ascii=False))
    assert len(parsed['segments'])==1
    merged,_=merge_segments(old,parsed,8,16)
    assert len(merged)==2 and '0.01' in merged[0]['source']
    assert merged[-1]['provisional']
    corrected={'replace_last':entry('A lower error does not guarantee lower test error.','较低的误差并不保证较低的测试误差。'),'segments':[]}
    final,_=merge_segments(merged,corrected,16,24)
    assert len(final)==2 and 'lower test error' in final[-1]['source']


@pytest.mark.parametrize('repair_kind',['correction','separate','failure'])
def test_short_shared_opening_is_relistened_not_blindly_deduplicated(monkeypatch,repair_kind):
    draft=entry('A lower training error indicates better fit on training data.',provisional=True)
    actual=entry('A lower training error does not necessarily mean a lower test error.',
                 '较低的训练误差并不一定意味着较低的测试误差。')
    calls=[]
    class Response:
        status_code=200;ok=True
        def __init__(self,content):self.content=content
        def json(self):return {'choices':[{'message':{'content':json.dumps(self.content)},'finish_reason':'stop'}]}
    def post(url,**kw):
        calls.append(kw['json'])
        if len(calls)==1:return Response({'segments':[actual]})
        if repair_kind=='failure':return Response({'invalid':'no usable repair'})
        return Response(dict(actual,consume=1 if repair_kind=='correction' else 0,complete=True))
    client=AudioClient('test');monkeypatch.setattr(client.session,'post',post)
    parsed,metric=client.translate(b'RIFF',Settings(),[draft],5,13,False,threading.Event())
    merged,_=merge_segments([draft],parsed,8,16)
    assert len(calls)==2 and metric['boundary_rechecks']==1 and metric['api_requests']==2
    if repair_kind=='correction':
        assert len(merged)==1 and merged[0]['source']==actual['source']
    else:
        assert len(merged)==2
        assert merged[0]['uncertain']==(repair_kind=='failure')
