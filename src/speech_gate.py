"""Local speech activity only: no words, transcription, network, or model downloads."""
from dataclasses import dataclass
from pathlib import Path
import numpy as np
import onnxruntime as ort

STEP=512/16000

@dataclass
class SpeechEvidence:
    probabilities: np.ndarray
    duration: float

    def summary(self,start=0.,end=None):
        end=self.duration if end is None else min(end,self.duration)
        a=max(0,int(start/STEP));b=min(len(self.probabilities),int(np.ceil(end/STEP)))
        p=self.probabilities[a:b]
        voiced=float(np.count_nonzero(p>=.45)*STEP)
        # Require sustained speech evidence; isolated clicks must not open the gate.
        longest=run=0
        for flag in p>=.45:
            run=run+1 if flag else 0;longest=max(longest,run)
        return {'has_speech':bool(voiced>=.128 and longest>=3),'speech_seconds':round(min(voiced,max(0,end-start)),3),
                'peak_probability':round(float(p.max()) if p.size else 0.,3)}

    def pause_near(self,start,target,latest):
        a=max(start+3,target-2);b=min(self.duration,latest,target+2)
        candidates=[];run=0
        for i,p in enumerate(self.probabilities):
            t=(i+1)*STEP
            run=run+1 if p<.25 else 0
            if a<=t<=b and run*STEP>=.45:
                candidates.append(t-.18)
        return min(candidates,key=lambda t:abs(t-target)) if candidates else min(target,latest)


class SpeechGate:
    def __init__(self):
        model=Path(__file__).resolve().parent/'assets/silero_vad.onnx'
        opts=ort.SessionOptions();opts.intra_op_num_threads=1;opts.inter_op_num_threads=1
        self.session=ort.InferenceSession(str(model),sess_options=opts,providers=['CPUExecutionProvider'])

    def analyze(self,pcm,rate):
        audio=np.frombuffer(pcm,dtype='<i2').astype(np.float32)/32768
        duration=len(audio)/rate
        if not len(audio):return SpeechEvidence(np.zeros(0,dtype=np.float32),0)
        if float(np.max(np.abs(audio)))<.00015:
            return SpeechEvidence(np.zeros(int(np.ceil(duration/STEP)),dtype=np.float32),duration)
        # Only the detector gets gain adjustment; original audio stays intact for translation/recovery.
        peak=float(np.max(np.abs(audio)))
        if peak<.06:audio*=min(8.,.06/peak)
        if rate!=16000:
            if rate>16000:
                k=np.arange(-32,33,dtype=np.float32);cutoff=.45*16000/rate
                kernel=2*cutoff*np.sinc(2*cutoff*k)*np.hamming(len(k));kernel/=kernel.sum()
                audio=np.convolve(audio,kernel,mode='same')
            points=np.arange(int(duration*16000))*rate/16000
            audio=np.interp(points,np.arange(len(audio)),audio).astype(np.float32)
        state=np.zeros((2,1,128),dtype=np.float32);context=np.zeros((1,64),dtype=np.float32)
        probabilities=[]
        for i in range(0,len(audio),512):
            chunk=audio[i:i+512]
            if len(chunk)<512:chunk=np.pad(chunk,(0,512-len(chunk)))
            frame=np.concatenate((context,chunk.reshape(1,-1)),axis=1)
            probability,state=self.session.run(None,{'input':frame,'state':state,'sr':np.array(16000,dtype=np.int64)})
            context=frame[:,-64:];probabilities.append(float(probability.item()))
        return SpeechEvidence(np.array(probabilities,dtype=np.float32),duration)
