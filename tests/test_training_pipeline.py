"""Pipeline config isolation and parent/child protocol; never real training."""
import json,sys,unittest
from pathlib import Path
from unittest.mock import patch
from threading import Thread
import time
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'backend'))
import test_training_queue_store as fixtures
from workers import training_worker as worker

class TrainingPipelineTests(unittest.TestCase):
    def setUp(self):
        self.fixture=fixtures.TrainingStoreTests();self.fixture.setUp();self.addCleanup(self.fixture.doCleanups)
        f=self.fixture;self.root=f.root;self.upstream=self.root/'upstream';(self.upstream/'GPT_SoVITS/configs').mkdir(parents=True)
        self.work=f.jobs/('b'*32);self.work.mkdir();self.experiment=self.root/'experiment';self.experiment.mkdir()
        (self.upstream/'GPT_SoVITS/configs/s2v2Pro.json').write_text('{"train":{},"model":{},"data":{}}',encoding='utf8')
        (self.upstream/'GPT_SoVITS/configs/s1longer-v2.yaml').write_text('train: {}\n',encoding='utf8')
    def test_training_configs_write_only_task_private_weight_paths(self):
        with patch.object(worker,'GPT_SOVITS_ROOT',self.upstream),patch.object(worker,'run_command'):
            worker.train_sovits('fixture',self.experiment,self.work,self.work/'log')
            worker.train_gpt('fixture',self.experiment,self.work,self.work/'log')
        sovits=json.loads((self.work/'s2_config.json').read_bytes())
        import yaml
        gpt=yaml.safe_load((self.work/'s1_config.yaml').read_text(encoding='utf8'))
        self.assertEqual(Path(sovits['save_weight_dir']),self.work/'weights/sovits')
        self.assertEqual(Path(gpt['train']['half_weights_save_dir']),self.work/'weights/gpt')
        self.assertFalse((self.upstream/'SoVITS_weights_v2Pro').exists());self.assertFalse((self.upstream/'GPT_weights_v2Pro').exists())
    def test_child_pipeline_protocol_emits_candidate_without_state_write(self):
        from workers.training_queue_worker import execute
        self.fixture.store.runtime=self.fixture.store.runtime.model_copy(update={'TRAINING_COMMAND_TIMEOUT':'.03'})
        job=self.fixture.create();folder=self.fixture.store.folder(job['job_id'])
        def fake_pipeline(identity,*,runtime):
            from services import training_command
            self.assertEqual(training_command._runner.timeout,.03)
            self.assertEqual(identity,job['job_id']);self.fixture.candidate(job)
            runtime.update(identity,job_status='preparing',progress=12,current_step='fixture')
            runtime.update(identity,job_status='completed',progress=100,current_step='Training completed',model_path='ignored')
        before=(folder/'state.json').read_bytes()
        with patch.object(worker,'run_training_job',fake_pipeline):self.assertEqual(execute(folder/'request.json'),0)
        self.assertEqual((folder/'state.json').read_bytes(),before)
        candidate=json.loads((folder/'candidate.json').read_bytes());self.assertEqual(candidate['request_sha256'],job['request_sha256'])
        progress=json.loads((folder/'progress.json').read_bytes());self.assertLess(progress['progress'],100)

    def test_legacy_runtime_snapshots_all_inputs_before_build(self):
        from workers.training_queue_worker import PipelineRuntime
        from schemas.training import TrainingRequest
        request=TrainingRequest(character_id='actor',model_name='legacy',stored_filename=self.fixture.fixture.source.name,transcript_filename='a'*32+'.json')
        job=self.fixture.store.create(request);protocol=self.fixture.store.request(job)
        folder=self.fixture.store.folder(job['job_id']);runtime=PipelineRuntime(protocol,folder,job['request_sha256'])
        work=self.fixture.jobs/job['job_id'];work.mkdir()
        directory,audio,annotation,metadata=runtime.prepare_legacy(job,'legacy_fixture',work)
        self.assertTrue(directory.is_relative_to(work));self.assertTrue(annotation.is_file())
        self.assertEqual((audio/self.fixture.fixture.source.name).read_bytes(),self.fixture.fixture.source.read_bytes())
        self.assertEqual(metadata['training_input_provenance']['source_hashes'],protocol.fingerprints)
        self.assertEqual(sorted(path.name for path in self.fixture.fixture.service.root.iterdir()),['prepared'])
    def test_progress_publish_survives_brief_windows_reader_sharing(self):
        from workers.training_queue_worker import PipelineRuntime
        job=self.fixture.create();request=self.fixture.store.request(job);folder=self.fixture.store.folder(job['job_id'])
        runtime=PipelineRuntime(request,folder,job['request_sha256'])
        runtime.update(job['job_id'],job_status='preparing',progress=5,current_step='Preparing')
        errors=[]
        def write():
            try:runtime.update(job['job_id'],job_status='preparing',progress=12,current_step='Text')
            except Exception as error:errors.append(error)
        with (folder/'progress.json').open('rb'):
            thread=Thread(target=write);thread.start();time.sleep(.08)
        thread.join(2)
        self.assertFalse(thread.is_alive());self.assertEqual(errors,[])
        self.assertEqual(json.loads((folder/'progress.json').read_bytes())['progress'],12)

if __name__=='__main__':unittest.main()
