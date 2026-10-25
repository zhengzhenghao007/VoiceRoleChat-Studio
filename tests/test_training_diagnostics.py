"""Bounded error diagnostics; no real upstream scripts or model loads."""
import json,sys,unittest
from unittest.mock import patch
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'backend'))
from schemas.training_queue import Progress
from services.training_command import CommandError
from workers import training_worker
from workers.training_queue_worker import PipelineRuntime
import test_training_queue as fixtures

class TrainingDiagnosticTests(unittest.TestCase):
    def test_exception_mapping_never_exposes_unknown_text(self):
        for code in ('timed_out','exit_nonzero','cancelled','ownership_failed','cleanup_failed','closed'):
            self.assertEqual(training_worker.failure_code(CommandError(code)),'command_'+code)
        for error in (RuntimeError('SECRET/path'),CommandError('SECRET/path')):
            self.assertEqual(training_worker.failure_code(error),'pipeline_failed')
    def test_phase_code_survive_parent_reap_and_reload(self):
        fixture=fixtures.TrainingQueueTests();fixture.setUp();self.addCleanup(fixture.doCleanups)
        queue=fixture.queue;job=fixture.submit();queue.tick();owner=fixture.owners[-1]
        folder=queue.store.folder(job['job_id']);runtime=PipelineRuntime(queue.store.request(job),folder,job['request_sha256'])
        runtime.update(job['job_id'],job_status='training',progress=55,current_step='Training SoVITS v2Pro')
        runtime.update(job['job_id'],job_status='failed',error_code='command_timed_out',error='SECRET',current_step='Training failed')
        raw=(folder/'progress.json').read_text();self.assertNotIn('SECRET',raw)
        owner.code=2;queue.tick();result=queue.get(job['job_id'])
        self.assertEqual(result['status'],'failed');self.assertEqual(result['error_code'],'command_timed_out')
        self.assertIn('SoVITS',result['current_step']);self.assertEqual(result['progress'],55)
        self.assertTrue(owner.closed);self.assertEqual(queue.store.load(job['job_id'])['error_code'],'command_timed_out')
        data=json.loads(raw);data['error_code']='arbitrary';
        from pydantic import ValidationError
        with self.assertRaises(ValidationError):Progress.model_validate(data)
    def test_old_progress_and_cancel_priority(self):
        fixture=fixtures.TrainingQueueTests();fixture.setUp();self.addCleanup(fixture.doCleanups)
        queue=fixture.queue;job=fixture.submit();queue.tick();folder=queue.store.folder(job['job_id'])
        runtime=PipelineRuntime(queue.store.request(job),folder,job['request_sha256'])
        runtime.update(job['job_id'],job_status='failed',error_code='command_exit_nonzero')
        queue.cancel(job['job_id']);queue.tick()
        self.assertEqual(queue.get(job['job_id'])['status'],'cancelled')
        data=json.loads((folder/'progress.json').read_bytes());data['error_code']='pipeline_failed';Progress.model_validate(data)
    def test_log_io_failure_never_masks_error_or_creates_missing_log(self):
        import tempfile
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'missing.log'
            training_worker.record_failure(path,'command_timed_out');self.assertFalse(path.exists())
            path.write_text('previous\n',encoding='utf8')
            with patch.object(training_worker.os,'open',side_effect=PermissionError('SECRET')):
                training_worker.record_failure(path,'command_timed_out')
            self.assertEqual(path.read_text(encoding='utf8'),'previous\n')
    def test_unknown_runtime_code_and_phase_redacted(self):
        fixture=fixtures.TrainingQueueTests();fixture.setUp();self.addCleanup(fixture.doCleanups)
        job=fixture.submit();folder=fixture.queue.store.folder(job['job_id'])
        runtime=PipelineRuntime(fixture.queue.store.request(job),folder,job['request_sha256'])
        runtime.update(job['job_id'],job_status='training',current_step='SECRET/private/path')
        runtime.update(job['job_id'],job_status='failed',error_code='SECRET/code',error='SECRET')
        data=json.loads((folder/'progress.json').read_bytes())
        self.assertEqual(data['error_code'],'pipeline_failed');self.assertEqual(data['current_step'],'Training failed')
        self.assertNotIn('SECRET',json.dumps(data))

if __name__=='__main__':unittest.main()
