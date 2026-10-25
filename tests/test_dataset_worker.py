"""Actual local decode, resampling and exact reviewed windows, without ML."""
from pathlib import Path
from fractions import Fraction
import hashlib,json,sys,tempfile,unittest,wave
import numpy as np
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'backend'))
from workers.dataset_worker import execute
from schemas.segmented_dataset import DatasetWorkerResult

class DatasetWorkerTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name);self.identity='a'*32;self.folder=self.root/('.staging-'+self.identity);self.folder.mkdir()
        self.path=self.folder/'request.json'
    def source(self,rate=32000,signal=None,extension='wav'):
        signal=signal if signal is not None else (.2*np.sin(2*np.pi*220*np.arange(rate*4)/rate)*32767).astype(np.int16)
        path=self.folder/('input.'+extension)
        if extension=='wav':
            with wave.open(str(path),'wb') as handle:
                handle.setparams((1,2,rate,0,'NONE',''));handle.writeframes(signal.astype('<i2').tobytes())
        else:
            import av
            with av.open(str(path),'w',format='flac') as output:
                stream=output.add_stream('flac',rate=rate);stream.layout='mono'
                frame=av.AudioFrame.from_ndarray(signal.reshape(1,-1),format='s16',layout='mono');frame.sample_rate=rate;frame.pts=0;frame.time_base=Fraction(1,rate)
                for packet in stream.encode(frame):output.mux(packet)
                for packet in stream.encode(None):output.mux(packet)
        request=dict(schema_version=1,task_id=self.identity,run_nonce='b'*32,source_filename='c'*32+'.'+extension,source_sha256=hashlib.sha256(path.read_bytes()).hexdigest(),windows=[dict(start=.25,end=1.25),dict(start=2,end=3.5)])
        self.path.write_text(json.dumps(request),encoding='utf8');return request,signal
    def result(self):return DatasetWorkerResult.model_validate(json.loads((self.folder/'worker-result.json').read_bytes()))
    def test_exact_native_pcm_windows_and_quality(self):
        request,signal=self.source();before=(self.folder/'input.wav').read_bytes()
        self.assertEqual(execute(self.path),0);result=self.result();self.assertEqual(len(result.clips),2)
        for clip,window in zip(result.clips,request['windows']):
            with wave.open(str(self.folder/clip.filename)) as handle:
                self.assertEqual((handle.getnchannels(),handle.getframerate(),handle.getsampwidth()),(1,32000,2))
                start,end=round(window['start']*32000),round(window['end']*32000)
                self.assertEqual(handle.getnframes(),end-start)
                self.assertEqual(handle.readframes(end-start),signal[start:end].astype('<i2').tobytes())
            self.assertGreater(clip.peak,0);self.assertLess(clip.rms_dbfs,0)
        self.assertEqual((self.folder/'input.wav').read_bytes(),before)
    def test_resampling_flush_and_real_compressed_format(self):
        for extension in ('wav','flac'):
            request,_=self.source(16000,extension=extension);request['windows']=[dict(start=2.5,end=4)]
            self.path.write_text(json.dumps(request),encoding='utf8')
            self.assertEqual(execute(self.path),0)
            clip=self.result().clips[0];self.assertEqual(clip.frames,48000)
            self.assertAlmostEqual(self.result().source_duration_seconds,4)
    def test_silence_rejection_and_quiet_short_warnings(self):
        request,_=self.source(signal=np.zeros(128000,dtype=np.int16));self.assertEqual(execute(self.path),2)
        error=json.loads((self.folder/'worker-error.json').read_bytes());self.assertEqual(error['code'],'silence')
        request,_=self.source(signal=np.ones(128000,dtype=np.int16));request['windows']=[dict(start=0,end=.5)]
        self.path.write_text(json.dumps(request),encoding='utf8');self.assertEqual(execute(self.path),0)
        self.assertIn('short_clip',self.result().clips[0].warnings);self.assertIn('quiet_clip',self.result().clips[0].warnings)
    def test_outside_actual_source_and_invalid_windows(self):
        request,_=self.source();request['windows']=[dict(start=3.5,end=5)]
        self.path.write_text(json.dumps(request),encoding='utf8');self.assertEqual(execute(self.path),2)
        for windows in ([dict(start=0,end=.1)],[dict(start=0,end=2),dict(start=1,end=3)]):
            request['windows']=windows;self.path.write_text(json.dumps(request),encoding='utf8');self.assertEqual(execute(self.path),2)
    def test_changed_hash_truncation_and_malformed_protocol(self):
        request,_=self.source();(self.folder/'input.wav').write_bytes(b'bad');self.assertEqual(execute(self.path),2)
        self.path.write_bytes(b'{' );self.assertEqual(execute(self.path),2)
        request,_=self.source();path=self.folder/'input.wav';path.write_bytes(path.read_bytes()[:-1]);request['source_sha256']=hashlib.sha256(path.read_bytes()).hexdigest();self.path.write_text(json.dumps(request),encoding='utf8')
        self.assertEqual(execute(self.path),2)

    def test_processing_budget_and_clipping_warning(self):
        from unittest.mock import patch
        self.source()
        with patch('workers.dataset_worker.MAX_SAMPLES',100):self.assertEqual(execute(self.path),2)
        self.source(signal=np.full(128000,32767,dtype=np.int16));self.assertEqual(execute(self.path),0)
        self.assertIn('clipping',self.result().clips[0].warnings)

if __name__=='__main__':unittest.main()
