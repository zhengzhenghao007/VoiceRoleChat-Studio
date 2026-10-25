"""Temporary-only training preparation; no upstream command is executed."""
from pathlib import Path
import hashlib,json,sys,tempfile,unittest
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'backend'))
import test_segmented_datasets as fixtures
from workers import training_worker as worker
from schemas.training import TrainingRequest
from pydantic import ValidationError

class TrainingSafetyTests(unittest.TestCase):
    def setUp(self):
        self.fixture=fixtures.SegmentedDatasetTests();self.fixture.setUp();self.addCleanup(self.fixture.doCleanups)
        f=self.fixture;self.root=f.root;self.datasets=f.service.root
        self.data=f.service.build(f.request());self.prepared=self.datasets/'prepared'
        self.jobs=self.root/'jobs';self.jobs.mkdir();self.models=self.root/'models';self.models.mkdir()
        self.upstream=self.root/'upstream';self.upstream.mkdir()
        for key,value in dict(DATASETS_DIR=self.datasets,UPLOAD_DIR=f.uploads,TRANSCRIPTS_DIR=f.records,CHARACTERS_DIR=f.characters,TRAINING_JOBS_DIR=self.jobs,MODELS_DIR=self.models,GPT_SOVITS_ROOT=self.upstream).items():
            p=patch.object(worker,key,value);p.start();self.addCleanup(p.stop)
        self.job=dict(job_id='c'*32,character_id='actor',model_name='test',engine='gpt_sovits',stored_filename=f.source.name,transcript_filename='a'*32+'.json')
    def test_legacy_collision_preserves_existing_dataset(self):
        marker=self.prepared/'keep';marker.write_text('keep')
        with self.assertRaises(Exception):worker.prepare_dataset(self.job,'prepared')
        self.assertEqual(marker.read_text(),'keep')
    def test_prepared_dataset_read_only_and_integrity(self):
        from services.training_dataset import validate_prepared_dataset
        before={str(p.relative_to(self.prepared)):p.read_bytes() for p in self.prepared.rglob('*') if p.is_file()}
        result=validate_prepared_dataset(self.datasets,'prepared','actor')
        self.assertEqual(result[0],self.prepared);self.assertEqual(result[2],self.prepared/'transcript.list')
        self.assertEqual(before,{str(p.relative_to(self.prepared)):p.read_bytes() for p in self.prepared.rglob('*') if p.is_file()})
        clip=self.prepared/'audio/segment_0001.wav';clip.write_bytes(clip.read_bytes()[:-2]+b'xx')
        with self.assertRaises(Exception):validate_prepared_dataset(self.datasets,'prepared','actor')
    def test_prepared_labels_snapshot_and_identity_rejected(self):
        from services.training_dataset import validate_prepared_dataset
        for name in ('transcript.list','review.json','dataset.json'):
            p=self.prepared/name;original=p.read_bytes();p.write_bytes(original+b'x')
            with self.subTest(name=name),self.assertRaises(Exception):validate_prepared_dataset(self.datasets,'prepared','actor')
            p.write_bytes(original)
        with self.assertRaises(Exception):validate_prepared_dataset(self.datasets,'prepared','other')
        with self.assertRaises(Exception):validate_prepared_dataset(self.datasets,'../prepared','actor')
    def test_request_grammar(self):
        valid=TrainingRequest(character_id='actor',model_name='test',dataset_name='prepared')
        self.assertEqual(valid.dataset_name,'prepared')
        for data in [dict(dataset_name='prepared',stored_filename='a.wav',transcript_filename='a.json'),dict(stored_filename='a.wav'),{},dict(dataset_name='../out'),dict(dataset_name='CON'),dict(dataset_name='prepared',engine='cosyvoice')]:
            with self.subTest(data=data),self.assertRaises(ValidationError):TrainingRequest(character_id='actor',model_name='x',**data)
    def test_log_work_export_collisions_prevent_commands(self):
        for index,kind in enumerate(('log','work','export')):
            self.job['job_id']=str(index+1)*32
            experiment=worker.safe_experiment_name('test',self.job['job_id'])
            target={'log':self.upstream/'logs'/experiment,'work':self.jobs/self.job['job_id'],'export':self.models/self.job['job_id']}[kind]
            with self.subTest(kind=kind):
                target.mkdir(parents=True,exist_ok=True);marker=target/'keep';marker.write_text('keep')
                with patch.object(worker,'get_training_job',return_value=self.job),patch.object(worker,'update_training_job'),patch.object(worker,'run_command') as command:
                    worker.run_training_job(self.job['job_id'])
                self.assertFalse(command.called,'No training command may start');self.assertEqual(marker.read_text(),'keep')
    def test_export_collision_preserves_weights(self):
        for directory,filename in [('SoVITS_weights_v2Pro','x_e1.pth'),('GPT_weights_v2Pro','x-e1.ckpt')]:
            p=self.upstream/directory;p.mkdir();(p/filename).write_bytes(b'weight')
        folder=self.models/self.job['job_id'];folder.mkdir();marker=folder/'gpt_v2pro.ckpt';marker.write_bytes(b'old')
        with self.assertRaises(Exception):worker.export_models(self.job['job_id'],'x',{})
        self.assertEqual(marker.read_bytes(),b'old')
    def test_existing_log_file_preserved_before_commands(self):
        log=self.jobs/(self.job['job_id']+'.log');log.write_text('old log')
        with patch.object(worker,'get_training_job',return_value=self.job),patch.object(worker,'update_training_job'),patch.object(worker,'run_command') as command:
            worker.run_training_job(self.job['job_id'])
        self.assertFalse(command.called,'No training command may start');self.assertEqual(log.read_text(),'old log')
    def test_existing_global_weights_prevent_commands(self):
        experiment=worker.safe_experiment_name('test',self.job['job_id'])
        folder=self.upstream/'GPT_weights_v2Pro';folder.mkdir()
        weight=folder/(experiment+'-e1.ckpt');weight.write_bytes(b'old weight')
        with patch.object(worker,'get_training_job',return_value=self.job),patch.object(worker,'update_training_job'),patch.object(worker,'run_command') as command:
            worker.run_training_job(self.job['job_id'])
        self.assertFalse(command.called,'No training command may start');self.assertEqual(weight.read_bytes(),b'old weight')
    def test_partial_training_dataset_survives_annotation_failure(self):
        original=Path.write_text
        def fail_annotation(path,*args,**kwargs):
            if path.name=='transcript.list' and path.parent.name.startswith('test_'):
                raise OSError('injected annotation write failure')
            return original(path,*args,**kwargs)
        before=(self.prepared/'dataset.json').read_bytes()
        with patch.object(Path,'write_text',fail_annotation),patch.object(worker,'get_training_job',return_value=self.job),patch.object(worker,'update_training_job'),patch.object(worker,'run_command') as command:
            worker.run_training_job(self.job['job_id'])
        self.assertFalse(command.called,'No training command may start')
        output=self.datasets/worker.safe_experiment_name('test',self.job['job_id'])
        self.assertTrue((output/'audio'/self.fixture.source.name).is_file())
        self.assertEqual((self.prepared/'dataset.json').read_bytes(),before)
    def test_worker_prepared_uses_task_snapshot_without_legacy_build(self):
        self.job.update(dataset_name='prepared',stored_filename=None,transcript_filename=None)
        with patch.object(worker,'get_training_job',return_value=self.job),patch.object(worker,'update_training_job'),patch.object(worker,'prepare_dataset') as legacy,patch.object(worker,'build_preprocessing_environment',return_value={}) as environment,patch.object(worker,'run_command',side_effect=RuntimeError('test stops before subprocess')):
            worker.run_training_job(self.job['job_id'])
        legacy.assert_not_called();snapshot=self.jobs/self.job['job_id']/'inputs/prepared'
        self.assertEqual(environment.call_args.args[:2],(snapshot/'transcript.list',snapshot/'audio'))
        self.assertTrue((self.jobs/self.job['job_id']/'input-provenance.json').is_file())
    def test_worker_snapshot_failure_never_runs_commands(self):
        self.job.update(dataset_name='prepared',stored_filename=None,transcript_filename=None)
        with patch.object(worker,'get_training_job',return_value=self.job),patch.object(worker,'update_training_job'),patch.object(worker,'create_verified_training_snapshot',side_effect=OSError('copy failed')),patch.object(worker,'run_command') as command:
            worker.run_training_job(self.job['job_id'])
        self.assertFalse(command.called,'No command after snapshot failure')

    def test_legacy_new_output_and_path_rejection(self):
        directory,_,annotation,metadata=worker.prepare_dataset(self.job,'fresh')
        self.assertEqual(directory,self.datasets/'fresh');self.assertTrue(annotation.is_file())
        for change in [dict(character_id='../actor'),dict(stored_filename='../escape.wav'),dict(transcript_filename='../escape.json')]:
            with self.subTest(change=change),self.assertRaises(Exception):worker.prepare_dataset(dict(self.job,**change),'other')
    def test_exclusive_create_race_and_unresolvable_path(self):
        from services.training_dataset import exclusive_directory
        original=Path.mkdir;target=self.datasets/'raced'
        def race(path,*args,**kwargs):
            if path==target and not path.exists():original(path);(path/'keep').write_text('racer')
            return original(path,*args,**kwargs)
        with patch.object(Path,'mkdir',race),self.assertRaises(FileExistsError):exclusive_directory(self.datasets,'raced')
        self.assertEqual((target/'keep').read_text(),'racer')
        with patch.object(Path,'resolve',side_effect=RuntimeError('loop')),self.assertRaises(Exception):exclusive_directory(self.datasets,'loop')
    def test_training_api_validates_before_thread_and_legacy_records(self):
        from fastapi.testclient import TestClient
        from fastapi import FastAPI
        from api import training
        from services import training_service
        app=FastAPI();app.include_router(training.router)
        with patch.multiple(training_service,CHARACTERS_DIR=self.fixture.characters,DATASETS_DIR=self.datasets,UPLOAD_DIR=self.fixture.uploads,TRANSCRIPTS_DIR=self.fixture.records,TRAINING_JOBS_DIR=self.jobs),patch.object(training,'Thread') as thread,TestClient(app) as client:
            response=client.post('/api/training/start',json=dict(character_id='actor',model_name='test',dataset_name='prepared'))
            self.assertEqual(response.status_code,201,response.text);thread.return_value.start.assert_called_once()
            job=response.json();self.assertEqual(job['dataset_name'],'prepared')
            self.assertEqual(client.get('/api/training/'+job['job_id']).status_code,200)
            thread.reset_mock()
            for change in [dict(dataset_name='missing'),dict(dataset_name='prepared',engine='cosyvoice'),dict(dataset_name='../bad'),dict(stored_filename='../bad',transcript_filename='x.json')]:
                response=client.post('/api/training/start',json=dict(character_id='actor',model_name='test',**change))
                self.assertEqual(response.status_code,422,response.text)
            thread.assert_not_called()
            response=client.post('/api/training/start',json={key:self.job[key] for key in ('character_id','model_name','stored_filename','transcript_filename')})
            self.assertEqual(response.status_code,201,response.text)
            old=dict(response.json());old.pop('dataset_name');(self.jobs/(old['job_id']+'.json')).write_text(json.dumps(old),encoding='utf8')
            self.assertIsNone(client.get('/api/training/'+old['job_id']).json()['dataset_name'])

if __name__=='__main__':unittest.main()
