import json
from pathlib import Path
import sys
import threading
import numpy as np
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src'))
from audio_engine import TranslationSession,list_devices
from core import Settings

def session(tmp_path,seconds=45):
    rate=16000
    s=TranslationSession('test-key',Settings(segment_seconds=18),{'rate':rate},tmp_path/'recording')
    signal=(np.sin(np.arange(rate*seconds)*.04)*10000).astype('<i2').tobytes()
    s.pcm_path.write_bytes(signal);s.samples=rate*seconds;s.capture_done.set()
    return s,signal

def test_failure_keeps_audio_and_retry_resumes_same_boundary(tmp_path):
    s,raw=session(tmp_path)
    # This test isolates retry/cursor safety; speech discrimination has real-audio tests below.
    from speech_gate import SpeechEvidence
    class Gate:
        def analyze(self,pcm,rate):return SpeechEvidence(np.ones(int(len(pcm)/2/rate/.032)+1),len(pcm)/2/rate)
    s.gate=Gate()
    calls=[]
    def fail(*args,**kwargs):calls.append(1);raise ValueError('模拟网络中断')
    s.client.translate=fail;s._process()
    assert s.failed and s.cursor==0 and s.pcm_path.read_bytes()==raw
    def good(audio,settings,history,prefix,focus,final,cancel,**kwargs):
        return {'segments':[{'source':f'Sentence {len(history)}.','zh':f'句子 {len(history)}。'}]}, {'seconds':.01}
    s.client.translate=good;s.failed=False;s._process()
    assert not s.failed and s.cursor==45 and len(s.entries)==3
    assert s.pcm_path.read_bytes()==raw
    assert [x['audio_start'] for x in s.metrics]==[0,18,36]

def test_recovery_uses_actual_audio_size_when_manifest_is_stale(tmp_path):
    s,raw=session(tmp_path,30)
    # Manifest at start intentionally says zero samples. Crash must not lose already captured PCM.
    r=TranslationSession.recover(s.path,'test-key')
    assert r.available==30 and r.cursor==0 and r.pcm_path.read_bytes()==raw

def test_digital_silence_is_not_sent_to_model(tmp_path):
    s,_=session(tmp_path,12);s.pcm_path.write_bytes(b'\0'*(12*16000*2))
    def fail(*args):raise AssertionError('Silent audio should not be uploaded')
    s.client.translate=fail;s._process()
    assert not s.failed and s.cursor==12 and not s.entries


def test_microphone_discovery_without_default_output_excludes_loopbacks_and_duplicates(monkeypatch):
    def device(index,host,loop=False):
        return {'index':index,'name':f'Device {index}','hostApi':host,'maxInputChannels':2,
                'defaultSampleRate':48000,'isLoopbackDevice':loop}
    devices=[device(0,0),device(1,2),device(2,2,True),device(3,2)]
    class Audio:
        def __enter__(self):return self
        def __exit__(self,*args):pass
        def get_host_api_info_by_type(self,kind):return {'index':2,'defaultInputDevice':3}
        def get_device_count(self):return len(devices)
        def get_device_info_by_index(self,i):return devices[i]
        def get_default_wasapi_loopback(self):raise LookupError('no default output')
        def get_loopback_device_info_generator(self):return iter([devices[2]])
    monkeypatch.setattr('audio_engine.pa.PyAudio',Audio)
    microphones=list_devices('microphone')
    assert [d['index'] for d in microphones]==[3,1]
    assert microphones[0]['default'] and all(d['kind']=='microphone' for d in microphones)
    assert [d['index'] for d in list_devices('system')]==[2]


def test_microphone_capture_routes_selected_input_and_saves_recoverable_mono(tmp_path,monkeypatch):
    import audio_engine
    device={'index':7,'rate':48000,'channels':2,'name':'USB microphone','kind':'microphone'}
    s=TranslationSession('test-key',Settings(source_kind='microphone'),device,tmp_path/'mic')
    opened={}
    class Stream:
        def is_active(self):return True
        def stop_stream(self):pass
        def close(self):pass
    class Audio:
        def open(self,**kwargs):
            opened.update(kwargs)
            frames=np.tile(np.array([.2,.4],dtype=np.float32),(1024,1))
            kwargs['stream_callback'](frames.tobytes(),1024,{},0)
            s.stop_capture.set()
            return Stream()
        def terminate(self):pass
    monkeypatch.setattr(audio_engine.pa,'PyAudio',Audio)
    s._capture();s._persist()
    assert opened['input'] and opened['input_device_index']==7 and opened['channels']==2
    assert s.recording_started and not s.capture_error and s.capture_done.is_set()
    mono=np.frombuffer(s.pcm_path.read_bytes(),dtype='<i2')
    assert mono.size==1024 and np.all(np.abs(mono-9830)<=1)
    recovered=TranslationSession.recover(s.path,'test-key')
    assert recovered.settings.source_kind=='microphone' and recovered.device['name']=='USB microphone'


def test_detector_failure_does_not_advance_or_upload(tmp_path):
    s,raw=session(tmp_path,12)
    class BadGate:
        def analyze(self,*args):raise RuntimeError('detector unavailable')
    s.gate=BadGate()
    def fail(*args,**kwargs):raise AssertionError('must not upload without speech verification')
    s.client.translate=fail;s._process()
    assert s.failed and s.cursor==0 and s.pcm_path.read_bytes()==raw


def test_background_noise_is_filtered_before_api_with_history(tmp_path):
    s,_=session(tmp_path,12)
    s.entries=[{'source':'Do not invent this sentence.','zh':'不要凭空生成这句话。'}]
    rng=np.random.default_rng(32)
    raw=(rng.normal(0,100,12*16000)).astype('<i2').tobytes();s.pcm_path.write_bytes(raw)
    def fail(*args,**kwargs):raise AssertionError('noise must not be uploaded')
    s.client.translate=fail;s._process()
    assert not s.failed and s.cursor==12 and len(s.entries)==1
    assert s.skipped[0]['reason']=='no_speech' and s.pcm_path.read_bytes()==raw
