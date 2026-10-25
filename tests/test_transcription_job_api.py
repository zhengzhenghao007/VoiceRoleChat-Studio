"""Real HTTP routes with isolated owned-worker fixtures, no model loading."""
from pathlib import Path
import sys,tempfile,time,unittest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'backend'))
from fastapi.testclient import TestClient
from app import app
from api.transcriptions import get_jobs
from services.transcription_job_service import TranscriptionJobs
from test_transcription_jobs import Worker

class JobAPITests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name);self.uploads=self.root/'uploads';self.uploads.mkdir()
        self.name='a'*32+'.wav';(self.uploads/self.name).write_bytes(b'test')
        self.jobs=TranscriptionJobs(self.root/'transcripts',self.uploads,worker_factory=lambda:Worker(),autostart=False)
        self.addCleanup(self.jobs.close);app.dependency_overrides[get_jobs]=lambda:self.jobs
        self.addCleanup(app.dependency_overrides.clear)
        self.client=TestClient(app);self.addCleanup(self.client.close)
    def test_submit_list_detail_result_and_terminal_cancel(self):
        created=self.client.post('/api/transcriptions/jobs',json=dict(stored_filename=self.name,language='ja'))
        self.assertEqual(created.status_code,202,created.text);identity=created.json()['id']
        self.assertEqual(self.client.get('/api/transcriptions/jobs').json()['items'][0]['id'],identity)
        self.assertEqual(self.client.get('/api/transcriptions/jobs/'+identity).json()['state'],'queued')
        self.assertEqual(self.client.get('/api/transcriptions/jobs/'+identity+'/result').status_code,409)
        self.jobs._tick();self.jobs._tick()
        result=self.client.get('/api/transcriptions/jobs/'+identity+'/result')
        self.assertEqual(result.status_code,200,result.text);self.assertEqual(result.json()['text'],'hello')
        self.assertEqual(self.client.post('/api/transcriptions/jobs/'+identity+'/cancel').json()['state'],'succeeded')
    def test_errors_queue_capacity_and_cancel(self):
        self.assertEqual(self.client.post('/api/transcriptions/jobs',json=dict(stored_filename=self.name,timeout=1)).status_code,422)
        self.assertEqual(self.client.get('/api/transcriptions/jobs/not-an-id').status_code,404)
        self.assertEqual(self.client.post('/api/transcriptions/jobs',json=dict(stored_filename='../x.wav')).status_code,404)
        self.assertEqual(self.client.post('/api/transcriptions/jobs',json=dict(stored_filename=self.name,language='zz')).status_code,422)
        identities=[self.client.post('/api/transcriptions/jobs',json=dict(stored_filename=self.name)).json()['id'] for _ in range(5)]
        self.assertEqual(self.client.post('/api/transcriptions/jobs',json=dict(stored_filename=self.name)).status_code,429)
        self.assertEqual(self.client.post('/api/transcriptions/jobs/'+identities[0]+'/cancel').json()['state'],'cancelled')
    def test_scheduler_thread_and_close_cancel_queue(self):
        jobs=TranscriptionJobs(self.root/'threaded',self.uploads,worker_factory=lambda:Worker(),autostart=True)
        try:
            created=jobs.submit(self.name,'ja');deadline=time.monotonic()+3
            while jobs.get(created['id'])['state'] not in ('succeeded','failed') and time.monotonic()<deadline:time.sleep(.01)
            self.assertEqual(jobs.get(created['id'])['state'],'succeeded')
        finally:jobs.close()
        self.assertFalse(jobs._thread.is_alive())

    def test_global_lifecycle_has_one_owner_across_concurrent_getters(self):
        from api import transcriptions as api
        from unittest.mock import patch,Mock
        from concurrent.futures import ThreadPoolExecutor
        manager=Mock()
        with patch.object(api,'_jobs',None),patch.object(api,'TranscriptionJobs',return_value=manager) as factory:
            with ThreadPoolExecutor(8) as pool:instances=list(pool.map(lambda _:api.get_jobs(),range(8)))
            self.assertTrue(all(item is manager for item in instances));self.assertEqual(factory.call_count,1)
            api.close_jobs();api.close_jobs();manager.close.assert_called_once()

if __name__=='__main__':unittest.main()
