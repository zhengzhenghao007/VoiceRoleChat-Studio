"""Immutable segmented publication with real codec fixtures and owned stubs."""
from pathlib import Path
import json,sys,tempfile,unittest,wave
from unittest.mock import patch
import numpy as np
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'backend'))
from services.segmented_dataset_service import SegmentedDatasets,DatasetError,cleanup_retained,cleanup_stage
from services.transcript_review_service import TranscriptReviews
from schemas.transcript_review import ReviewCreate,ReviewUpdate
from schemas.segmented_dataset import SegmentDatasetRequest
from services.owned_worker import OwnershipError
from workers.dataset_worker import execute

class Worker:
    def __init__(self,mode='success',hook=None):self.mode=mode;self.hook=hook;self.owned=False;self.code=None
    def start(self,command,cwd=None):
        self.owned=True
        if self.mode=='launch':raise OwnershipError('fail')
        if self.mode in ('wait','cleanup'):return
        self.code=execute(Path(command[-1]));folder=Path(cwd)
        if self.mode=='wrong':
            path=folder/'worker-result.json';data=json.loads(path.read_bytes());data['run_nonce']='0'*32;path.write_text(json.dumps(data),encoding='utf8')
        if self.mode=='bad_wave':(folder/'audio/segment_0001.wav').write_bytes(b'invalid')
        if self.hook:self.hook()
    def poll(self):return self.code
    def stop(self,timeout=2):
        if self.owned and self.mode=='cleanup':raise OwnershipError('stuck')
        self.owned=False
    close=stop

class SegmentedDatasetTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name);self.uploads=self.root/'uploads';self.uploads.mkdir()
        self.source=self.uploads/('b'*32+'.wav')
        signal=(np.sin(2*np.pi*220*np.arange(128000)/32000)*6000).astype('<i2')
        with wave.open(str(self.source),'wb') as handle:handle.setparams((1,2,32000,0,'NONE',''));handle.writeframes(signal.tobytes())
        self.records=self.root/'transcripts';self.records.mkdir();raw=dict(stored_filename=self.source.name,language='ja',language_probability=1.,duration=4.,text='first second',segments=[dict(start=0,end=1,text='first'),dict(start=2,end=3,text='second')])
        source_id='a'*32;(self.records/(source_id+'.json')).write_text(json.dumps(raw),encoding='utf8')
        self.reviews=TranscriptReviews(self.records,self.uploads);doc=self.reviews.get(source_id)
        self.review=self.reviews.create(ReviewCreate(source_id=source_id,expected_source_sha256=doc['sha256'],language='ja',segments=raw['segments']))
        self.characters=self.root/'characters';(self.characters/'actor').mkdir(parents=True)
        (self.characters/'actor'/'config.json').write_text('{"name":"Actor"}',encoding='utf8')
        self.mode='success';self.hook=None;self.workers=[]
        def factory():
            worker=Worker(self.mode,self.hook);self.workers.append(worker);return worker
        self.service=SegmentedDatasets(self.root/'datasets',self.uploads,self.reviews,self.characters,worker_factory=factory,timeout=5)
        self.addCleanup(self.cleanup)
    def cleanup(self):
        for worker in self.workers:worker.mode='success'
        cleanup_retained()
    def request(self,name='prepared'):
        return SegmentDatasetRequest(character_id='actor',review_id=self.review['id'],expected_revision=self.review['revision'],expected_sha256=self.review['sha256'],dataset_name=name)
    def test_real_slices_final_annotations_and_no_overwrite(self):
        original=self.source.read_bytes();result=self.service.build(self.request())
        self.assertEqual(result['entry_count'],2);self.assertEqual(result['total_duration'],2)
        final=self.service.root/'prepared';lines=(final/'transcript.list').read_text(encoding='utf8').splitlines()
        self.assertEqual(len(lines),2)
        for index,line in enumerate(lines,1):
            path,speaker,language,text=line.split('|');self.assertEqual(Path(path),final/'audio'/f'segment_{index:04d}.wav')
            self.assertEqual((speaker,language),('Actor','ja'))
            with wave.open(path) as handle:self.assertEqual(handle.getnframes(),32000)
        self.assertEqual(self.source.read_bytes(),original)
        self.assertFalse((final/'input.wav').exists());self.assertFalse((final/'request.json').exists())
        self.assertEqual(json.loads((final/'review.json').read_bytes())['id'],self.review['id'])
        before=(final/'dataset.json').read_bytes()
        with self.assertRaises(DatasetError) as error:self.service.build(self.request())
        self.assertEqual(error.exception.status_code,409);self.assertEqual((final/'dataset.json').read_bytes(),before)
        self.assertEqual(self.service.get('prepared')['entry_count'],2)
    def test_stale_review_and_review_changed_during_decode(self):
        request=self.request();self.hook=lambda:self.reviews.update(self.review['id'],ReviewUpdate(expected_revision=self.review['revision'],expected_sha256=self.review['sha256'],language='ja',segments=[dict(start=0,end=1,text='new')]))
        with self.assertRaises(DatasetError) as error:self.service.build(request)
        self.assertEqual(error.exception.status_code,409);self.assertFalse((self.service.root/'prepared').exists())
        with self.assertRaises(DatasetError):self.service.build(request)
    def test_bad_output_deadline_and_cleanup_retention(self):
        for mode,code in [('wrong',503),('bad_wave',503),('launch',503),('wait',504)]:
            self.mode=mode
            self.service.timeout=.03 if mode=='wait' else 5
            with self.assertRaises(DatasetError) as error:self.service.build(self.request(mode))
            self.assertEqual(error.exception.status_code,code,mode)
            self.assertFalse((self.service.root/mode).exists());self.assertEqual(list(self.service.root.glob('.staging-*')),[])
        self.mode='cleanup'
        self.service.timeout=.03
        with self.assertRaises(DatasetError) as error:self.service.build(self.request('cleanup'))
        self.assertEqual(error.exception.status_code,503);self.assertEqual(len(list(self.service.root.glob('.staging-*'))),1)
        with self.assertRaises(DatasetError):self.service.build(self.request('blocked'))
        self.workers[-1].mode='success';cleanup_retained();self.assertEqual(list(self.service.root.glob('.staging-*')),[])
    def test_injection_language_and_missing_source(self):
        character=self.characters/'actor'/'config.json';character.write_text('{"name":"bad|speaker"}',encoding='utf8')
        with self.assertRaises(DatasetError) as error:self.service.build(self.request())
        self.assertEqual(error.exception.status_code,422)
        character.write_text('{"name":"Actor"}',encoding='utf8')
        for language,text in [('ja','bad|text'),('ja','line\nbreak'),('fr','normal')]:
            self.review=self.reviews.update(self.review['id'],ReviewUpdate(expected_revision=self.review['revision'],expected_sha256=self.review['sha256'],language=language,segments=[dict(start=0,end=1,text=text)]))
            with self.assertRaises(DatasetError) as error:self.service.build(self.request())
            self.assertEqual(error.exception.status_code,422)
        self.review=self.reviews.update(self.review['id'],ReviewUpdate(expected_revision=self.review['revision'],expected_sha256=self.review['sha256'],language='ja',segments=[dict(start=0,end=1,text='normal')]))
        self.source.unlink()
        with self.assertRaises(DatasetError):self.service.build(self.request())
    def test_rename_failure_cleanup_preserves_existing_datasets(self):
        existing=self.service.root/'keep';existing.mkdir(parents=True);(existing/'data').write_bytes(b'keep')
        with patch('services.segmented_dataset_service.os.rename',side_effect=OSError('disk')):
            with self.assertRaises(DatasetError):self.service.build(self.request())
        self.assertEqual((existing/'data').read_bytes(),b'keep');self.assertEqual(list(self.service.root.glob('.staging-*')),[])
    def test_readonly_legacy_future_and_path_diagnostics(self):
        legacy=self.service.root/'legacy';legacy.mkdir(parents=True)
        path=legacy/'dataset.json';path.write_text('{"experiment_name":"legacy","language":"ja","text":"old"}',encoding='utf8');before=path.read_bytes()
        future=self.service.root/'future';future.mkdir();(future/'dataset.json').write_text('{"schema_version":99}',encoding='utf8')
        listing=self.service.list();self.assertEqual(len(listing['items']),1);self.assertEqual(len(listing['diagnostics']),1)
        self.assertEqual(path.read_bytes(),before)
        for name in ('../x','CON','x/y'):
            with self.assertRaises(DatasetError):self.service.get(name)

    def test_concurrent_build_is_rejected_and_source_mutation_blocks_publish(self):
        import threading
        entered,release=threading.Event(),threading.Event()
        self.hook=lambda:(entered.set(),release.wait(5))
        result=[]
        thread=threading.Thread(target=lambda:result.append(self.service.build(self.request())))
        thread.start()
        try:
            self.assertTrue(entered.wait(2))
            with self.assertRaises(DatasetError) as error:self.service.build(self.request('second'))
            self.assertEqual(error.exception.status_code,429)
        finally:release.set();thread.join(5)
        self.assertFalse(thread.is_alive());self.assertEqual(result[0]['entry_count'],2)
        self.hook=lambda:self.source.write_bytes(self.source.read_bytes()+b'x')
        with self.assertRaises(DatasetError) as error:self.service.build(self.request('changed'))
        self.assertEqual(error.exception.status_code,409)
        self.assertFalse((self.service.root/'changed').exists())

    def test_decoded_duration_must_match_review_metadata(self):
        signal=(np.sin(2*np.pi*220*np.arange(160000)/32000)*6000).astype('<i2')
        with wave.open(str(self.source),'wb') as handle:handle.setparams((1,2,32000,0,'NONE',''));handle.writeframes(signal.tobytes())
        with self.assertRaises(DatasetError) as error:self.service.build(self.request())
        self.assertEqual(error.exception.status_code,422)
        self.assertFalse((self.service.root/'prepared').exists())

    def test_known_job_audio_hash_prevents_same_duration_replacement(self):
        import hashlib
        identity='e'*32
        raw=dict(stored_filename=self.source.name,language='ja',language_probability=1.,duration=4.,text='original',segments=[dict(start=0,end=1,text='original')],
            schema_version=2,id=identity,task_id=identity,run_nonce='f'*32,source_sha256=hashlib.sha256(self.source.read_bytes()).hexdigest(),revision=1,created_at='2026-10-25T00:00:00+00:00',transcript_file='transcripts/'+identity+'.json')
        (self.records/(identity+'.json')).write_text(json.dumps(raw),encoding='utf8');doc=self.reviews.get(identity)
        self.review=self.reviews.create(ReviewCreate(source_id=identity,expected_source_sha256=doc['sha256'],language='ja',segments=raw['segments']))
        content=bytearray(self.source.read_bytes());content[100:102]=b'\x01\x01';self.source.write_bytes(content)
        with self.assertRaises(DatasetError) as error:self.service.build(self.request())
        self.assertEqual(error.exception.status_code,409)
        self.assertFalse((self.service.root/'prepared').exists())

    def test_unresolvable_dataset_path_is_diagnostic_not_global_failure(self):
        valid=self.service.root/'valid';valid.mkdir(parents=True)
        (valid/'dataset.json').write_text('{"dataset_name":"valid"}',encoding='utf8')
        folder=self.service.root/'loop';folder.mkdir(parents=True)
        (folder/'dataset.json').write_text('{"dataset_name":"loop"}',encoding='utf8')
        resolve=Path.resolve
        def looping(path,*args,**kwargs):
            if path==folder:raise RuntimeError('link loop')
            return resolve(path,*args,**kwargs)
        with patch.object(Path,'resolve',looping):
            self.assertEqual(self.service.list()['diagnostics'],[dict(dataset_name='loop',code='invalid_or_future_metadata')])
            self.assertEqual(self.service.list()['items'][0]['dataset_name'],'valid')

    def test_cleanup_unresolvable_stage_refuses_deletion(self):
        stage=self.service.root/('.staging-'+'a'*32);stage.mkdir(parents=True)
        marker=stage/'keep.txt';marker.write_text('keep',encoding='utf8')
        resolve=Path.resolve
        def looping(path,*args,**kwargs):
            if path==stage:raise RuntimeError('link loop')
            return resolve(path,*args,**kwargs)
        with patch.object(Path,'resolve',looping),self.assertRaises(DatasetError) as error:
            cleanup_stage(self.service.root,stage)
        self.assertEqual(error.exception.status_code,503)
        self.assertEqual(marker.read_text(encoding='utf8'),'keep')

if __name__=='__main__':unittest.main()
