import sys,wave
from pathlib import Path
import numpy as np
import pytest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src'))
from speech_gate import SpeechGate

@pytest.fixture(scope='module')
def gate():return SpeechGate()

def pcm(a):return (np.clip(a,-1,1)*32767).astype('<i2').tobytes()

@pytest.mark.parametrize('kind',['silence','noise','hum','chord','clicks'])
def test_non_speech_is_rejected(gate,kind):
    rate=16000;n=rate*4;t=np.arange(n)/rate;rng=np.random.default_rng(82)
    signals={'silence':np.zeros(n),'noise':rng.normal(0,.003,n),
             'hum':.006*np.sin(2*np.pi*100*t),
             'chord':sum(.03*np.sin(2*np.pi*f*t) for f in (220,277.18,329.63)),
             'clicks':np.where(np.arange(n)%8000<160,rng.normal(0,.08,n),0)}
    assert not gate.analyze(pcm(signals[kind]),rate).summary()['has_speech']

@pytest.mark.parametrize('gain',[1,.02])
def test_normal_and_quiet_speech_survive(gate,gain):
    with wave.open(str(Path(__file__).parent/'assets/speech.wav'),'rb') as w:
        rate=w.getframerate();audio=np.frombuffer(w.readframes(w.getnframes()),dtype='<i2').astype(float)/32768
    assert gate.analyze(pcm(audio*gain),rate).summary()['has_speech']

def test_old_overlap_speech_cannot_open_silent_new_focus(gate):
    with wave.open(str(Path(__file__).parent/'assets/speech.wav'),'rb') as w:
        rate=w.getframerate();data=w.readframes(w.getnframes())
    duration=len(data)/2/rate
    evidence=gate.analyze(data+b'\0'*(rate*10*2),rate)
    assert evidence.summary(0,duration)['has_speech']
    assert not evidence.summary(duration+2,duration+10)['has_speech']
