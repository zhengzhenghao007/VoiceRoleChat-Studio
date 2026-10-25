"""Durable jobs with fake owned workers; all storage is temporary."""
from pathlib import Path
import json,sys,tempfile,time,unittest
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'backend'))
from services.transcription_job_service import TranscriptionJobs,JobError,read_json,atomic_json
from services.owned_worker import OwnershipError

class Worker:
    def __init__(self,mode='success'):self.mode=mode;self.owned=False;self.stopped=False
    def start(self,command,cwd=None):
        self.owned=True;self.folder=Path(cwd)
        request=read_json(self.folder/'request.json',16384)
        if self.mode=='start_error':raise OwnershipError('launch')
        transcript=dict(stored_filename=request['source_filename'],language='ja',language_probability=1.0,duration=4.0,text='hello',segments=[dict(start=0.0,end=3.0,text='hello')],transcript_file='transcripts/'+request['task_id']+'.json')
        candidate=dict(schema_version=1,task_id=request['task_id'],run_nonce=request['run_nonce'],source_filename=request['source_filename'],source_sha256=request['source_sha256'],transcript=transcript)
        if self.mode=='bad_nonce':candidate['run_nonce']='0'*32
        if self.mode=='large':(self.folder/'worker-result.json').write_bytes(b'x'*(8*1024*1024+1))
        else:atomic_json(self.folder/'worker-result.json',candidate)
    def poll(self):return None if self.mode in ('wait','cleanup_error') else (4 if self.mode=='crash' else 0)
    def stop(self,timeout=2):
        if self.owned and self.mode=='cleanup_error':raise OwnershipError('stuck')
        self.stopped=True;self.owned=False
    close=stop

class JobTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name);self.uploads=self.root/'uploads';self.uploads.mkdir()
        self.name='a'*32+'.wav';(self.uploads/self.name).write_bytes(b'original')
        self.mode='success';self.workers=[]
        def factory():
            worker=Worker(self.mode);self.workers.append(worker);return worker
        self.factory=factory
        self.jobs=TranscriptionJobs(self.root/'transcripts',self.uploads,worker_factory=factory,autostart=False,timeout=5)
        self.addCleanup(self.cleanup)
    def cleanup(self):
        for worker in self.workers:
            if worker.mode=='cleanup_error':worker.mode='wait'
        self.jobs.close()
    def submit(self):return self.jobs.submit(self.name,'ja')
    def finish(self):self.jobs._tick();self.jobs._tick()
    def test_success_unique_result_and_original_preserved(self):
        job=self.submit();self.assertEqual(job['state'],'queued');self.finish()
        done=self.jobs.get(job['id']);self.assertEqual(done['state'],'succeeded')
        result=read_json(self.root/'transcripts'/(job['id']+'.json'))
        self.assertEqual(result['text'],'hello');self.assertEqual(result['revision'],1)
        self.assertEqual((self.uploads/self.name).read_bytes(),b'original')
        self.assertFalse((self.root/'transcripts'/('a'*32+'.json')).exists())
        self.assertTrue(all(not worker.owned for worker in self.workers))
    def test_capacity_invalid_source_language_and_queued_cancel(self):
        for _ in range(5):self.submit()
        with self.assertRaises(JobError) as error:self.submit()
        self.assertEqual(error.exception.status_code,429)
        first=self.jobs.list()['items'][0];self.assertEqual(self.jobs.cancel(first['id'])['state'],'cancelled')
        self.assertEqual(self.jobs.cancel(first['id'])['state'],'cancelled');self.submit()
        for name in ('../x.wav','x.wav','b'*32+'.wav'):
            with self.assertRaises(JobError):self.jobs.submit(name)
        with self.assertRaises(JobError):self.jobs.submit(self.name,'zz')
    def test_cancel_running_wins_and_late_result_cannot_publish(self):
        self.mode='wait';job=self.submit();self.jobs._tick()
        pending=self.jobs.cancel(job['id']);self.assertEqual(pending['decision'],'cancelled')
        self.assertNotEqual(pending['state'],'cancelled');self.jobs._tick()
        self.assertEqual(self.jobs.get(job['id'])['state'],'cancelled')
        self.assertFalse((self.root/'transcripts'/(job['id']+'.json')).exists())
    def test_timeout_bad_protocol_start_failure_and_crash(self):
        for mode,expected in [('wait','timed_out'),('bad_nonce','failed'),('large','failed'),('start_error','failed'),('crash','failed')]:
            self.mode=mode;job=self.submit();self.jobs._tick()
            if mode=='wait':self.jobs._started-=10
            self.jobs._tick();self.assertEqual(self.jobs.get(job['id'])['state'],expected,mode)
            self.assertFalse((self.root/'transcripts'/(job['id']+'.json')).exists())
    def test_cleanup_failure_retains_owner_blocks_admission_then_shutdown_retries(self):
        self.mode='cleanup_error';job=self.submit();self.jobs._tick();self.jobs.cancel(job['id']);self.jobs._tick()
        self.assertNotEqual(self.jobs.get(job['id'])['state'],'cancelled')
        with self.assertRaises(JobError):self.submit()
        self.workers[-1].mode='wait';self.jobs.close()
        self.assertEqual(self.jobs.get(job['id'])['state'],'cancelled')
    def test_restart_interrupted_and_committed_result_reconciliation(self):
        queued=self.submit();self.mode='wait';running=self.submit();self.jobs._tick()
        # Simulate a crash only after explicitly releasing this test-owned fake child.
        self.jobs._worker.stop();self.jobs._worker=None;self.jobs._active_id=None
        recovered=TranscriptionJobs(self.jobs.root,self.uploads,worker_factory=self.factory,autostart=False)
        self.addCleanup(recovered.close)
        self.assertEqual(recovered.get(queued['id'])['state'],'interrupted')
        self.assertEqual(recovered.get(running['id'])['state'],'interrupted')
    def test_publish_commit_wins_over_cancel_when_state_write_failed(self):
        job=self.submit();self.jobs._tick();real=self.jobs._persist
        def fail_success(data):
            if data['state']=='succeeded':raise JobError('disk',503)
            return real(data)
        with patch.object(self.jobs,'_persist',side_effect=fail_success):self.jobs._tick()
        self.assertEqual(self.jobs.cancel(job['id'])['state'],'succeeded')
        recovered=TranscriptionJobs(self.jobs.root,self.uploads,worker_factory=self.factory,autostart=False)
        self.addCleanup(recovered.close);self.assertEqual(recovered.get(job['id'])['state'],'succeeded')
    def test_corrupt_future_and_escape_are_diagnostic_read_only(self):
        job=self.submit();path=self.jobs.root/'.jobs'/job['id']/'state.json'
        data=read_json(path);data['schema_version']=99;atomic_json(path,data)
        malformed=self.jobs.root/'.jobs'/('f'*32);malformed.mkdir();(malformed/'state.json').write_bytes(b'{')
        before=path.read_bytes();recovered=TranscriptionJobs(self.jobs.root,self.uploads,worker_factory=self.factory,autostart=False)
        self.addCleanup(recovered.close);listing=recovered.list();self.assertEqual(len(listing['diagnostics']),2)
        self.assertEqual(path.read_bytes(),before)
    def test_atomic_failure_never_replaces_old_result(self):
        path=self.root/'atomic.json';atomic_json(path,{'old':True})
        with patch('services.transcription_job_service.os.replace',side_effect=OSError('disk')):
            with self.assertRaises(JobError):atomic_json(path,{'new':True})
        self.assertEqual(read_json(path),{'old':True});self.assertEqual(list(self.root.glob('*.tmp')),[])

    def test_progress_protocol_and_failed_cancel_persistence(self):
        self.mode='wait';job=self.submit();self.jobs._tick()
        progress=self.jobs.root/'.jobs'/job['id']/'progress.json'
        atomic_json(progress,dict(schema_version=1,run_nonce=job['run_nonce'],phase='transcribing'))
        self.jobs._tick();self.assertEqual(self.jobs.get(job['id'])['phase'],'transcribing')
        atomic_json(progress,dict(schema_version=1,run_nonce='0'*32,phase='transcribing'))
        self.jobs._tick();self.assertEqual(self.jobs.get(job['id'])['state'],'failed')
        self.mode='success';second=self.submit();self.jobs._tick()
        with patch.object(self.jobs,'_persist',side_effect=JobError('disk')):
            with self.assertRaises(JobError):self.jobs.cancel(second['id'])
        self.jobs._tick();self.assertEqual(self.jobs.get(second['id'])['state'],'succeeded')

    def test_concurrent_capacity_and_close_are_bounded(self):
        from concurrent.futures import ThreadPoolExecutor
        def submit(_):
            try:return self.submit()['id']
            except JobError as error:return error.status_code
        with ThreadPoolExecutor(8) as pool:results=list(pool.map(submit,range(8)))
        self.assertEqual(results.count(429),3)
        self.assertEqual(len(set(value for value in results if isinstance(value,str))),5)
        self.jobs.close();self.jobs.close()
        self.assertTrue(all(job['state']=='cancelled' for job in self.jobs.list()['items']))

    def test_shutdown_storage_failure_still_reaps_and_can_retry(self):
        self.mode='wait';job=self.submit();self.jobs._tick();worker=self.jobs._worker
        with patch.object(self.jobs,'_persist',side_effect=JobError('disk')):
            with self.assertRaises(JobError):self.jobs.close()
        self.assertFalse(worker.owned)
        self.jobs.close();self.assertEqual(self.jobs.get(job['id'])['state'],'cancelled')

    def test_cancel_intent_recovery_and_invalid_committed_identity(self):
        self.mode='wait';job=self.submit();self.jobs._tick();self.jobs.cancel(job['id'])
        self.jobs._worker.stop();self.jobs._worker=None;self.jobs._active_id=None
        recovered=TranscriptionJobs(self.jobs.root,self.uploads,worker_factory=self.factory,autostart=False)
        self.addCleanup(recovered.close);self.assertEqual(recovered.get(job['id'])['state'],'cancelled')
        self.mode='success';other=self.submit();self.finish()
        path=self.jobs.root/(other['id']+'.json');data=read_json(path);data['run_nonce']='0'*32;atomic_json(path,data)
        with self.assertRaises(JobError):self.jobs.result(other['id'])

    def test_result_publication_failure_preserves_other_records(self):
        sentinel=self.jobs.root/'existing.json';sentinel.write_bytes(b'keep')
        job=self.submit();self.jobs._tick();real=__import__('services.transcription_job_service',fromlist=['atomic_json']).atomic_json
        def fail_result(path,data,*args):
            if Path(path).parent==self.jobs.root:raise JobError('disk')
            return real(path,data,*args)
        with patch('services.transcription_job_service.atomic_json',side_effect=fail_result):self.jobs._tick()
        self.assertEqual(self.jobs.get(job['id'])['state'],'failed')
        self.assertEqual(sentinel.read_bytes(),b'keep')

if __name__=='__main__':unittest.main()
