"""Queue arbitration with controllable owned-process substitutes; no GPU."""
import sys,time,unittest,json
from pathlib import Path
from unittest.mock import patch
from threading import Event,Thread
from uuid import UUID
import subprocess
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'backend'))
import test_training_queue_store as fixtures
from services.training_queue import TrainingQueue
from services.training_queue_store import QueueError
from services.owned_worker import OwnershipError

class Owner:
    def __init__(self,fixture):self.fixture=fixture;self.code=None;self.fail=False;self.closed=False
    def start(self,command,cwd=None):
        self.identity=Path(command[-1]).parent.name;self.fixture.owners.append(self)
    def poll(self):return self.code
    def close(self):
        if self.fail:raise OwnershipError('cleanup pending')
        self.closed=True
    def finish(self):
        self.fixture.candidate(self.fixture.queue.get(self.identity));self.code=0

class TrainingQueueTests(unittest.TestCase):
    def setUp(self):
        self.fixture=fixtures.TrainingStoreTests();self.fixture.setUp();self.addCleanup(self.fixture.doCleanups)
        f=self.fixture;self.owners=[]
        def factory():
            return Owner(self)
        self.queue=TrainingQueue(f.jobs,f.models,f.runtime,worker_factory=factory,autostart=False,timeout=10)
        self.fixture.queue=self.queue;self.addCleanup(self.cleanup)
    def candidate(self,job):return self.fixture.candidate(job)
    def cleanup(self):
        for owner in self.owners:owner.fail=False
        self.queue.close()
    def submit(self):return self.queue.submit(self.fixture.request)
    def test_fifo_capacity_cancel_queued_and_terminal_idempotence(self):
        first=self.submit();self.queue.tick();self.assertEqual(self.owners[-1].identity,first['job_id'])
        rest=[self.submit() for _ in range(5)];before=len(list(self.queue.store.directory.iterdir()))
        with self.assertRaises(QueueError) as error:self.submit()
        self.assertEqual(error.exception.status_code,429);self.assertEqual(len(list(self.queue.store.directory.iterdir())),before)
        cancelled=self.queue.cancel(rest[0]['job_id']);self.assertEqual(cancelled['status'],'cancelled')
        self.owners[-1].finish();self.queue.tick();self.assertEqual(self.queue.get(first['job_id'])['status'],'completed')
        self.queue.tick();self.assertEqual(self.owners[-1].identity,rest[1]['job_id'])
        self.assertEqual(self.queue.cancel(first['job_id'])['status'],'completed')
    def test_cancel_wins_before_commit_and_cleanup_failure_blocks(self):
        job=self.submit();self.queue.tick();owner=self.owners[-1];owner.finish();owner.fail=True
        requested=self.queue.cancel(job['job_id']);self.assertEqual(requested['decision'],'cancelled');self.assertNotEqual(requested['status'],'cancelled')
        self.queue.tick();self.assertNotEqual(self.queue.get(job['job_id'])['status'],'cancelled')
        with self.assertRaises(QueueError):self.submit()
        self.assertFalse((self.fixture.models/job['job_id']).exists())
        owner.fail=False;self.queue.tick();self.assertEqual(self.queue.get(job['job_id'])['status'],'cancelled')
    def test_task_deadline_excludes_queue_wait(self):
        job=self.submit();self.queue.timeout=.02;time.sleep(.03);self.assertEqual(self.queue.get(job['job_id'])['status'],'queued')
        self.queue.tick();self.assertEqual(self.queue.get(job['job_id'])['status'],'preparing')
        time.sleep(.03);self.queue.tick();self.assertEqual(self.queue.get(job['job_id'])['status'],'timed_out')
    def test_changed_source_while_queued_never_starts(self):
        job=self.submit();source=self.fixture.fixture.service.root/'prepared/dataset.json';source.write_bytes(source.read_bytes()+b' ')
        self.queue.tick();self.assertEqual(self.queue.get(job['job_id'])['status'],'failed');self.assertFalse(self.owners)
    def test_committed_model_recovers_after_final_state_write_failure(self):
        job=self.submit();self.queue.tick();self.owners[-1].finish();original=self.queue.store.persist
        def failing(data):
            if data['status']=='completed':raise QueueError('injected post-commit state write failure')
            return original(data)
        with patch.object(self.queue.store,'persist',failing):self.queue.tick()
        self.assertTrue(self.queue.store.committed(job));self.queue.close()
        self.queue=TrainingQueue(self.fixture.jobs,self.fixture.models,self.fixture.runtime,autostart=False)
        self.assertEqual(self.queue.get(job['job_id'])['status'],'completed')
    def test_root_lease_and_shutdown_no_resume(self):
        with self.assertRaises(QueueError):TrainingQueue(self.fixture.jobs,self.fixture.models,self.fixture.runtime,autostart=False)
        job=self.submit();self.queue.tick();queued=self.submit();self.queue.close()
        self.assertEqual(self.queue.get(job['job_id'])['status'],'interrupted');self.assertEqual(self.queue.get(queued['job_id'])['status'],'interrupted')
        self.queue=TrainingQueue(self.fixture.jobs,self.fixture.models,self.fixture.runtime,autostart=False)
        self.assertFalse(self.queue._worker);self.assertEqual(self.queue.get(job['job_id'])['status'],'interrupted')
    def test_recovery_does_not_rewrite_future_or_legacy(self):
        self.queue.close();job=self.fixture.store.create(self.fixture.request)
        folder=self.fixture.store.folder('f'*32);folder.mkdir();path=folder/'state.json';path.write_text('{"schema_version":99}',encoding='utf8');before=path.read_bytes()
        self.queue=TrainingQueue(self.fixture.jobs,self.fixture.models,self.fixture.runtime,autostart=False)
        self.assertEqual(self.queue.get(job['job_id'])['status'],'interrupted');self.assertEqual(path.read_bytes(),before)
        self.assertTrue(any(item['job_id']=='f'*32 for item in self.queue.diagnostics()))
    def test_cancel_persistence_failure_does_not_acknowledge_or_kill(self):
        job=self.submit();self.queue.tick();owner=self.owners[-1]
        with patch.object(self.queue.store,'persist',side_effect=QueueError('disk full')),self.assertRaises(QueueError):self.queue.cancel(job['job_id'])
        self.assertIsNone(self.queue.get(job['job_id'])['decision']);self.assertFalse(owner.closed)

    def test_fifo_when_created_timestamps_are_equal(self):
        with patch('services.training_queue_store.now',return_value='same'),patch('services.training_queue_store.uuid4',side_effect=[UUID('f'*32),UUID('1'*32),UUID('a'*32),UUID('2'*32)]):
            first=self.submit();self.submit()
        self.queue.tick();self.assertEqual(self.owners[-1].identity,first['job_id'])
    def test_cancel_during_candidate_verification_wins(self):
        job=self.submit();self.queue.tick();self.owners[-1].finish();entered=Event();resume=Event();original=self.queue.store.validate_export
        def validating(record):
            entered.set();resume.wait(5);return original(record)
        with patch.object(self.queue.store,'validate_export',validating):
            thread=Thread(target=self.queue.tick);thread.start();self.assertTrue(entered.wait(3))
            self.queue.cancel(job['job_id']);resume.set();thread.join(5)
        self.assertFalse(thread.is_alive());self.assertEqual(self.queue.get(job['job_id'])['status'],'cancelled')
        self.assertFalse((self.fixture.models/job['job_id']).exists())
    def test_cross_process_training_root_exclusion(self):
        code="import sys;sys.path.insert(0,sys.argv[1]);from services.training_queue import RootLease;from services.training_queue_store import QueueError\ntry:lease=RootLease(sys.argv[2])\nexcept QueueError:raise SystemExit(0)\nelse:lease.close();raise SystemExit(1)"
        result=subprocess.run([sys.executable,'-c',code,str(Path(__file__).resolve().parents[1]/'backend'),str(self.queue.store.directory/'manager.lock')],capture_output=True,timeout=10)
        self.assertEqual(result.returncode,0)
    def test_shutdown_cleans_active_process_even_when_state_storage_fails(self):
        job=self.submit();self.queue.tick();owner=self.owners[-1]
        with patch.object(self.queue.store,'persist',side_effect=QueueError('disk full')):
            try:self.queue.close()
            except QueueError:pass
        self.assertTrue(owner.closed,'Backend shutdown must not leave a live owned pipeline when state storage fails')
    def test_injected_monotonic_deadline(self):
        self.queue.close();clock=[0.0]
        self.queue=TrainingQueue(self.fixture.jobs,self.fixture.models,self.fixture.runtime,worker_factory=lambda:Owner(self),autostart=False,timeout=1,clock=lambda:clock[0])
        job=self.submit();self.queue.tick();clock[0]=1.01;self.queue.tick()
        self.assertEqual(self.queue.get(job['job_id'])['status'],'timed_out')
    def test_deadline_reaps_even_if_timeout_intent_cannot_be_saved(self):
        clock=[0.0];self.queue.clock=lambda:clock[0];self.queue.timeout=1
        job=self.submit();self.queue.tick();owner=self.owners[-1];clock[0]=1.01
        with patch.object(self.queue.store,'persist',side_effect=QueueError('disk full')),self.assertRaises(QueueError):self.queue.tick()
        self.assertTrue(owner.closed,'Task deadline still stops the owned process if intent persistence fails')
        self.assertNotEqual(self.queue.get(job['job_id'])['status'],'timed_out')
        with self.assertRaises(QueueError):self.submit()

if __name__=='__main__':unittest.main()
