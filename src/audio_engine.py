from __future__ import annotations
import json
import os
from pathlib import Path
import threading
import time
import uuid
import numpy as np
import pyaudiowpatch as pa
from PySide6.QtCore import QObject, Signal
from core import Settings, AudioClient, app_data, atomic_json, wav_bytes, merge_segments
from speech_gate import SpeechGate

class Events(QObject):
    changed = Signal(object)
    status = Signal(str)
    error = Signal(str)
    level = Signal(float)
    stats = Signal(object)
    stopped = Signal()
    preview = Signal(object)

def list_devices(kind='system'):
    """List WASAPI render loopbacks or physical inputs, without duplicate host APIs."""
    if kind not in ('system','microphone'):
        raise ValueError('未知的声音来源')
    with pa.PyAudio() as p:
        if kind=='system':
            # A missing default output must not hide other connected devices.
            try:default_index=p.get_default_wasapi_loopback()['index']
            except (OSError,LookupError):default_index=-1
            devices=list(p.get_loopback_device_info_generator())
        else:
            host=p.get_host_api_info_by_type(pa.paWASAPI)
            default_index=host.get('defaultInputDevice',-1)
            devices=[p.get_device_info_by_index(i) for i in range(p.get_device_count())]
            devices=[d for d in devices if d['hostApi']==host['index']
                     and d['maxInputChannels']>0 and not d.get('isLoopbackDevice',False)]
        devices=[d for d in devices if d['maxInputChannels']>0]
        devices.sort(key=lambda d:d['index']!=default_index)
        return [{'index':d['index'],'name':d['name'],'rate':int(d['defaultSampleRate']),
                 'channels':d['maxInputChannels'],'default':d['index']==default_index,'kind':kind} for d in devices]

class TranslationSession:
    """Capture writes PCM to disk; API processing reads sequentially, never drops a backlog."""
    def __init__(self, key:str, settings:Settings, device:dict, root:Path|None=None):
        self.events=Events()
        self.settings=settings
        self.client=AudioClient(key)
        self.device=device
        self.rate=device['rate']
        self.path=root or app_data()/'sessions'/(time.strftime('%Y%m%d-%H%M%S')+'-'+uuid.uuid4().hex[:6])
        self.path.mkdir(parents=True,exist_ok=True)
        self.pcm_path=self.path/'audio.pcm'
        self.entries=[]
        self.cursor=0.0
        self.samples=0
        self.capture_done=threading.Event()
        self.stop_capture=threading.Event()
        self.cancel=threading.Event()
        self.lock=threading.Lock()
        self.worker=None
        self.capture_thread=None
        self.last_level=0.0
        self.failed=False
        self.metrics=[]
        self.recording_started=False
        self.capture_error=''
        self.gate=None
        self.skipped=[]
        self._persist()

    @property
    def available(self):
        with self.lock:
            return self.samples/self.rate

    def _persist(self):
        atomic_json(self.path/'session.json',{'version':1,'topic':self.settings.topic,'glossary':self.settings.glossary,
            'language':self.settings.language,'segment_seconds':self.settings.segment_seconds,'sample_rate':self.rate,
            'source_kind':self.settings.source_kind,'device_name':self.device.get('name',''),
            'cursor':self.cursor,'audio_seconds':self.available,'entries':self.entries,'metrics':self.metrics,
            'filtered_spans':self.skipped})

    def start(self):
        self.capture_thread=threading.Thread(target=self._capture,daemon=True,name='wasapi-capture')
        self.worker=threading.Thread(target=self._process,daemon=True,name='omni-translation')
        self.capture_thread.start()
        self.worker.start()

    def finish(self):
        self.stop_capture.set()
        self.events.status.emit('正在结束收音，并翻译剩余内容…')

    def retry(self,key=None):
        if self.worker and self.worker.is_alive():
            return
        if key:
            self.client=AudioClient(key)
        self.failed=False
        self.cancel.clear()
        self.worker=threading.Thread(target=self._process,daemon=True,name='omni-retry')
        self.worker.start()

    def _capture(self):
        stream=None
        p=None
        try:
            p=pa.PyAudio()
            channels=self.device['channels']
            if channels<1:
                raise ValueError('所选设备不支持音频输入，请刷新后重新选择。')
            with self.pcm_path.open('wb') as out:
                def callback(data,frame_count,time_info,status):
                    try:
                        if status & pa.paInputOverflow:
                            self.events.error.emit('音频设备出现溢出，部分声音可能缺失。请停止并检查设备。')
                            self.stop_capture.set()
                        pcm=np.frombuffer(data,dtype=np.float32).reshape(-1,channels)
                        mono=pcm.mean(axis=1)
                        mono=np.nan_to_num(mono,nan=0.0,posinf=1.0,neginf=-1.0)
                        level=float(np.sqrt(np.mean(mono*mono))) if mono.size else 0.
                        encoded=(np.clip(mono,-1,1)*32767).astype('<i2').tobytes()
                        out.write(encoded)
                        out.flush()
                        with self.lock:
                            self.samples+=len(mono)
                        now=time.monotonic()
                        if now-self.last_level>.15:
                            self.events.level.emit(level)
                            self.last_level=now
                        return (None,pa.paComplete if self.stop_capture.is_set() else pa.paContinue)
                    except Exception as ex:
                        self.capture_error='音频采集异常：'+str(ex)
                        self.events.error.emit(self.capture_error)
                        self.stop_capture.set()
                        return (None,pa.paAbort)
                stream=p.open(format=pa.paFloat32,channels=channels,rate=self.rate,input=True,
                    input_device_index=self.device['index'],frames_per_buffer=1024,stream_callback=callback)
                self.recording_started=True
                source='麦克风' if self.settings.source_kind=='microphone' else '系统声音'
                self.events.status.emit('正在收听'+source+' · 等待第一段完整语境')
                while stream.is_active() and not self.stop_capture.wait(.1):
                    if self.available-self.cursor>150:
                        self.events.error.emit('翻译积压超过 150 秒，已停止收音并保留全部已采集音频。请暂停课程，等待处理。')
                        self.stop_capture.set()
                if not self.stop_capture.is_set():
                    self.capture_error='音频设备意外停止，已保存此前的音频。请检查所选设备连接。'
                    self.events.error.emit(self.capture_error)
                stream.stop_stream()
                stream.close()
                stream=None
        except Exception as ex:
            hint=' 请确认麦克风已连接，且 Windows 允许桌面应用使用麦克风。' if self.settings.source_kind=='microphone' else ''
            self.capture_error='收音失败：'+str(ex)+hint
            self.events.error.emit(self.capture_error)
        finally:
            if stream:
                stream.close()
            if p:
                p.terminate()
            self.capture_done.set()

    def read_audio(self,start,end):
        start_sample=max(0,int(start*self.rate))
        end_sample=min(int(end*self.rate),self.samples)
        with self.pcm_path.open('rb') as f:
            f.seek(start_sample*2)
            return f.read(max(0,end_sample-start_sample)*2)

    def _choose_end(self,start,available,final,evidence=None,left=0):
        target=self.settings.segment_seconds
        if final and available-start<=target+self.settings.lookahead:
            return available
        if evidence:
            return left+evidence.pause_near(start-left,start+target-left,available-self.settings.lookahead-left)
        return min(start+target,available)

    def _skip(self,end,reason,evidence):
        self.skipped.append({'start':self.cursor,'end':end,'reason':reason,**evidence})
        self.cursor=end;self._persist();self.events.preview.emit([])
        self.events.status.emit('未检测到可辨人声 · 继续等待讲话，背景声不生成文稿')
        self.events.stats.emit({'captured':self.available,'processed':self.cursor,'queued':self.available-self.cursor,
                               'filtered_seconds':sum(x['end']-x['start'] for x in self.skipped)})

    def _process(self):
        try:
            if self.gate is None:self.gate=SpeechGate()
            while not self.cancel.is_set():
                available=self.available
                done=self.capture_done.is_set()
                if done and available-self.cursor<.15:
                    break
                if available-self.cursor<self.settings.segment_seconds+self.settings.lookahead and not done:
                    self.events.stats.emit({'captured':available,'processed':self.cursor,'queued':available-self.cursor})
                    self.cancel.wait(.25)
                    continue
                if available<=0:
                    if done: break
                    self.cancel.wait(.25)
                    continue
                left=max(0,self.cursor-5)
                if self.entries and self.entries[-1].get('pending'):
                    left=max(0,min(left,self.entries[-1].get('start',left)),self.cursor-12)
                examine_end=min(available,self.cursor+self.settings.segment_seconds+self.settings.lookahead+2)
                evidence=self.gate.analyze(self.read_audio(left,examine_end),self.rate)
                end=self._choose_end(self.cursor,available,done,evidence,left)
                right=min(available,end+self.settings.lookahead)
                pcm=self.read_audio(left,right)
                # Only NEW focus speech can open the gate. Old overlap cannot trigger a silent interval.
                voice=evidence.summary(self.cursor-left,end-left)
                if not voice['has_speech']:
                    self._skip(end,'no_speech',voice)
                    continue
                self.events.status.emit('正在理解音频并翻译…')
                result,metric=self.client.translate(wav_bytes(pcm,self.rate),self.settings,self.entries,
                    self.cursor-left,end-left,done and right>=available,self.cancel,on_preview=self.events.preview.emit)
                if self.cancel.is_set():
                    break
                metric.update(audio_start=self.cursor,audio_end=end,audio_submitted=right-left,speech=voice)
                self.metrics.append(metric)
                if not result['segments'] and not result.get('replace_last'):
                    self._skip(end,'model_no_intelligible_speech',voice)
                    continue
                self.entries,_=merge_segments(self.entries,result,self.cursor,end)
                self.cursor=end
                self._persist()
                self.events.changed.emit(self.entries.copy())
                self.events.preview.emit([])
                self.events.stats.emit({'captured':self.available,'processed':self.cursor,'queued':self.available-self.cursor,
                    'request_seconds':metric['seconds'],'sentences':len(self.entries)})
                self.events.status.emit('正在收听 · 文稿已更新' if not done else '正在整理最后的文稿…')
            for item in self.entries:item['provisional']=False
            self.events.changed.emit(self.entries.copy())
            self._persist()
            self.events.stats.emit({'captured':self.available,'processed':self.cursor,'queued':self.available-self.cursor})
            if self.capture_error:
                self.events.status.emit('收音已中断 · 已保存此前的音频与文稿')
            elif not self.failed:
                self.events.status.emit('本次听课已结束 · 文稿已自动保存')
        except InterruptedError:
            self.events.status.emit('已停止处理 · 文稿与剩余音频已保存')
        except Exception as ex:
            self.failed=True
            self.stop_capture.set()
            self._persist()
            self.events.error.emit(str(ex))
        finally:
            self.events.preview.emit([])
            self.events.stopped.emit()

    @classmethod
    def recover(cls,path,key):
        path=Path(path)
        info=json.loads((path/'session.json').read_text(encoding='utf-8'))
        settings=Settings(topic=info.get('topic',''),glossary=info.get('glossary',''),
            language=info.get('language','自动识别'),segment_seconds=info.get('segment_seconds',18),
            source_kind=info.get('source_kind','system'))
        # Construct without overwriting the session manifest before reading PCM.
        self=cls.__new__(cls)
        self.events=Events(); self.settings=settings; self.client=AudioClient(key)
        self.device={'name':info.get('device_name','')}; self.rate=info['sample_rate']; self.path=path; self.pcm_path=path/'audio.pcm'
        self.entries=info['entries']; self.cursor=info['cursor']
        self.samples=self.pcm_path.stat().st_size//2
        self.capture_done=threading.Event(); self.capture_done.set()
        self.stop_capture=threading.Event(); self.stop_capture.set()
        self.cancel=threading.Event(); self.lock=threading.Lock()
        self.worker=None; self.capture_thread=None; self.failed=False; self.metrics=info.get('metrics',[])
        self.recording_started=False; self.last_level=0
        self.capture_error=''
        self.gate=None;self.skipped=info.get('filtered_spans',[])
        return self
