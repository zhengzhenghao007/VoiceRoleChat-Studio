"""Worker protocol and pure inference; generated PCM only, no ML model loads."""
from pathlib import Path
import io,json,sys,tempfile,unittest,wave
from types import SimpleNamespace
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'backend'))
from workers.transcription_worker import execute
from services.transcription_service import infer_path
from services.transcription_job_service import atomic_json,read_json

class WorkerProtocolTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.folder=Path(self.temp.name)/('b'*32);self.folder.mkdir()
        source=self.folder/'input.wav'
        with wave.open(str(source),'wb') as handle:
            handle.setnchannels(1);handle.setsampwidth(2);handle.setframerate(16000);handle.writeframes(b'\0\0'*64000)
        import hashlib
        self.request=dict(schema_version=1,task_id='b'*32,run_nonce='c'*32,source_filename='a'*32+'.wav',source_sha256=hashlib.sha256(source.read_bytes()).hexdigest(),language='ja',model_size='small',device='cpu',compute_type='int8')
        self.path=self.folder/'request.json';atomic_json(self.path,self.request)
        self.model=SimpleNamespace(transcribe=lambda *a,**k:(iter([SimpleNamespace(start=0,end=3,text=' hello ')]),SimpleNamespace(language='ja',language_probability=1.0,duration=4.0)))
    def factory(self,*args,**kwargs):
        self.assertTrue(kwargs['local_files_only']);return self.model
    def test_pure_inference_has_no_result_write_and_worker_binds_identity(self):
        result=infer_path(self.folder/'input.wav',self.request['source_filename'],'ja',self.model)
        self.assertEqual(result['text'],'hello');self.assertFalse((self.folder/'worker-result.json').exists())
        self.assertEqual(execute(self.path,model_factory=self.factory),0)
        candidate=read_json(self.folder/'worker-result.json')
        self.assertEqual(candidate['run_nonce'],self.request['run_nonce'])
        self.assertEqual(candidate['transcript']['transcript_file'],'transcripts/'+'b'*32+'.json')
        self.assertEqual(read_json(self.folder/'progress.json')['phase'],'transcribing')
    def test_missing_model_and_invalid_request_never_publish(self):
        def missing(*a,**k):raise OSError('private path')
        self.assertEqual(execute(self.path,model_factory=missing),3)
        for key,value in [('run_nonce','bad'),('task_id','d'*32),('unknown',True)]:
            changed=dict(self.request);changed[key]=value;atomic_json(self.path,changed)
            self.assertEqual(execute(self.path,model_factory=self.factory),2)
        self.assertFalse((self.folder/'worker-result.json').exists())
    def test_changed_snapshot_and_invalid_audio_rejected_before_model(self):
        (self.folder/'input.wav').write_bytes(b'not audio')
        self.assertEqual(execute(self.path,model_factory=lambda *a,**k:self.fail('Loaded model')),2)
        import hashlib
        self.request['source_sha256']=hashlib.sha256(b'not audio').hexdigest();atomic_json(self.path,self.request)
        self.assertEqual(execute(self.path,model_factory=lambda *a,**k:self.fail('Loaded model')),2)

if __name__=='__main__':unittest.main()
