"""Durable training store: isolated inputs, candidate weights are plain fixture bytes."""
import hashlib,json,sys,tempfile,unittest
from unittest.mock import patch
from types import SimpleNamespace
from pathlib import Path
from uuid import uuid4
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'backend'))
import test_segmented_datasets as fixtures
from schemas.training import TrainingRequest
from services.training_queue_store import TrainingStore,QueueError

class TrainingStoreTests(unittest.TestCase):
    def setUp(self):
        self.fixture=fixtures.SegmentedDatasetTests();self.fixture.setUp();self.addCleanup(self.fixture.doCleanups)
        f=self.fixture;self.root=f.root;self.jobs=self.root/'jobs';self.jobs.mkdir();self.models=self.root/'models';self.models.mkdir()
        f.service.build(f.request())
        self.runtime=dict(CHARACTERS_DIR=str(f.characters),DATASETS_DIR=str(f.service.root),TRANSCRIPTS_DIR=str(f.records),UPLOAD_DIR=str(f.uploads),TRAINING_JOBS_DIR=str(self.jobs),GPT_SOVITS_ROOT=str(self.root/'upstream'),GPT_SOVITS_PYTHON=sys.executable,GPT_SOVITS_GPU='0')
        for name in ('BERT_DIR','HUBERT_DIR','S1_MODEL','S2D_MODEL','S2G_MODEL','SV_MODEL'):self.runtime['GPT_SOVITS_'+name]=str(self.root/'unused'/name)
        self.store=TrainingStore(self.jobs,self.models,self.runtime)
        self.request=TrainingRequest(character_id='actor',model_name='fixture',dataset_name='prepared')
    def create(self):return self.store.create(self.request)
    def candidate(self,job):
        folder=self.store.folder(job['job_id']);stage=folder/'export'/job['job_id'];stage.mkdir(parents=True)
        work=self.jobs/job['job_id']/'weights';(work/'gpt').mkdir(parents=True);(work/'sovits').mkdir()
        gpt=work/'gpt/fixture-e1.ckpt';sovits=work/'sovits/fixture_e1.pth';gpt.write_bytes(b'fake GPT');sovits.write_bytes(b'fake SoVITS')
        (stage/'gpt_v2pro.ckpt').write_bytes(gpt.read_bytes());(stage/'sovits_v2pro.pth').write_bytes(sovits.read_bytes())
        manifest=dict(job_id=job['job_id'],character_id=job['character_id'],version='v2Pro',gpt_model=str(stage/'gpt_v2pro.ckpt'),sovits_model=str(stage/'sovits_v2pro.pth'),source_gpt_model=str(gpt),source_sovits_model=str(sovits))
        (stage/'manifest.json').write_text(json.dumps(manifest),encoding='utf8')
        sha=lambda path:hashlib.sha256(path.read_bytes()).hexdigest()
        candidate=dict(schema_version=1,job_id=job['job_id'],run_nonce=job['run_nonce'],request_sha256=job['request_sha256'],manifest_sha256=sha(stage/'manifest.json'),gpt_sha256=sha(stage/'gpt_v2pro.ckpt'),sovits_sha256=sha(stage/'sovits_v2pro.pth'))
        (folder/'candidate.json').write_text(json.dumps(candidate),encoding='utf8');return stage
    def test_state_request_and_input_binding(self):
        job=self.create();self.assertEqual(job['status'],'queued');self.assertEqual(job['schema_version'],1)
        loaded=self.store.request(job);self.assertEqual(loaded.job_id,job['job_id'])
        self.assertEqual(self.store.load(job['job_id']),job)
        source=self.fixture.service.root/'prepared/dataset.json';source.write_bytes(source.read_bytes()+b' ')
        with self.assertRaises(QueueError):self.store.verify_inputs(loaded)
    def test_request_tamper_and_future_state_readonly(self):
        job=self.create();path=self.store.folder(job['job_id'])/'request.json';path.write_bytes(path.read_bytes()+b' ')
        with self.assertRaises(QueueError):self.store.request(job)
        state=self.store.folder(job['job_id'])/'state.json';data=json.loads(state.read_bytes());data['schema_version']=99;state.write_text(json.dumps(data),encoding='utf8');before=state.read_bytes()
        with self.assertRaises(QueueError):self.store.load(job['job_id'])
        self.assertEqual(state.read_bytes(),before)
    def test_atomic_export_no_overwrite_and_commit_proof(self):
        job=self.create();self.candidate(job);prepared=self.store.validate_export(job)
        target=self.store.publish(job,prepared)
        self.assertEqual(target,self.models/job['job_id']);self.assertTrue(self.store.committed(job))
        manifest=json.loads((target/'manifest.json').read_bytes());self.assertEqual(manifest['gpt_model'],str(target/'gpt_v2pro.ckpt'))
        self.assertEqual(manifest['training_task']['run_nonce'],job['run_nonce'])
        before=(target/'gpt_v2pro.ckpt').read_bytes()
        with self.assertRaises(QueueError):self.store.publish(job,prepared)
        self.assertEqual((target/'gpt_v2pro.ckpt').read_bytes(),before)
    def test_invalid_candidate_never_publishes(self):
        job=self.create();stage=self.candidate(job);(stage/'gpt_v2pro.ckpt').write_bytes(b'tamper')
        with self.assertRaises(QueueError):self.store.validate_export(job)
        self.assertFalse((self.models/job['job_id']).exists())
    def test_legacy_record_projection_is_readonly(self):
        identity=uuid4().hex;data=dict(job_id=identity,character_id='actor',engine='cosyvoice',model_name='old',stored_filename='old.wav',transcript_filename='old.json',status='queued',progress=0,current_step='old',created_at='2020',updated_at='2020')
        path=self.jobs/(identity+'.json');path.write_text(json.dumps(data),encoding='utf8');before=path.read_bytes()
        self.assertEqual(self.store.legacy(identity)['engine'],'cosyvoice');self.assertEqual(path.read_bytes(),before)

    def test_oversized_candidate_rejected_before_hashing_payload(self):
        job=self.create();stage=self.candidate(job);weight=stage/'gpt_v2pro.ckpt';original=Path.stat
        def stat(path,*args,**kwargs):
            if path==weight:return SimpleNamespace(st_size=8*1024**3+1)
            return original(path,*args,**kwargs)
        from services import training_queue_store
        digest=training_queue_store.digest
        def hashing(path,limit):
            if Path(path)==weight:raise AssertionError('Oversized weight must be refused before reading payload')
            return digest(path,limit)
        with patch.object(Path,'stat',stat),patch.object(training_queue_store,'digest',hashing),self.assertRaises(QueueError):self.store.validate_export(job)
    def test_candidate_extra_file_or_wrong_character_rejected(self):
        job=self.create();stage=self.candidate(job);extra=stage/'unexpected.txt';extra.write_text('exclude',encoding='utf8')
        with self.assertRaises(QueueError):self.store.validate_export(job)
        extra.unlink();manifest_path=stage/'manifest.json';manifest=json.loads(manifest_path.read_bytes());manifest['character_id']='other'
        manifest_path.write_text(json.dumps(manifest),encoding='utf8')
        path=self.store.folder(job['job_id'])/'candidate.json';candidate=json.loads(path.read_bytes());candidate['manifest_sha256']=hashlib.sha256(manifest_path.read_bytes()).hexdigest();path.write_text(json.dumps(candidate),encoding='utf8')
        with self.assertRaises(QueueError):self.store.validate_export(job)
    def test_invalid_manifest_source_type_is_typed_rejection(self):
        job=self.create();stage=self.candidate(job)
        manifest_path=stage/'manifest.json';manifest=json.loads(manifest_path.read_bytes());manifest['source_gpt_model']={}
        manifest_path.write_text(json.dumps(manifest),encoding='utf8')
        path=self.store.folder(job['job_id'])/'candidate.json';candidate=json.loads(path.read_bytes());candidate['manifest_sha256']=hashlib.sha256(manifest_path.read_bytes()).hexdigest();path.write_text(json.dumps(candidate),encoding='utf8')
        with self.assertRaises(QueueError):self.store.validate_export(job)


if __name__=='__main__':unittest.main()
