"""Real API schema and queue dependency; no per-request training Thread."""
import sys,unittest,json
from unittest.mock import patch,Mock
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'backend'))
from fastapi import FastAPI
from fastapi.testclient import TestClient
from api import training
import test_training_queue_store as fixtures
from services.training_queue import TrainingQueue

class TrainingQueueAPITests(unittest.TestCase):
    def setUp(self):
        self.fixture=fixtures.TrainingStoreTests();self.fixture.setUp();self.addCleanup(self.fixture.doCleanups)
        f=self.fixture;self.queue=TrainingQueue(f.jobs,f.models,f.runtime,autostart=False);self.addCleanup(self.queue.close)
        app=FastAPI();app.include_router(training.router)
        app.dependency_overrides[training.get_training_queue]=lambda:self.queue
        self.client=TestClient(app);self.addCleanup(self.client.close)
        self.payload=self.fixture.request.model_dump(exclude_none=True)
    def test_start_list_detail_cancel_and_capacity(self):
        response=self.client.post('/api/training/start',json=self.payload);self.assertEqual(response.status_code,201,response.text)
        job=response.json();self.assertEqual(job['schema_version'],1);self.assertIsNone(self.queue._worker)
        self.assertEqual(self.client.get('/api/training/'+job['job_id']).status_code,200)
        response=self.client.post('/api/training/'+job['job_id']+'/cancel');self.assertEqual(response.status_code,202)
        self.assertEqual(response.json()['status'],'cancelled')
        for _ in range(5):self.assertEqual(self.client.post('/api/training/start',json=self.payload).status_code,201)
        self.assertEqual(self.client.post('/api/training/start',json=self.payload).status_code,429)
        self.assertEqual(len(self.client.get('/api/training').json()),6)
        self.assertEqual(self.client.get('/api/training/diagnostics').status_code,200)
        self.assertEqual(self.client.get('/api/training/not-an-id').status_code,404)
    def test_invalid_source_and_legacy_readonly(self):
        for changes in [dict(engine='cosyvoice'),dict(dataset_name='../escape'),dict(stored_filename='x.wav')]:
            self.assertEqual(self.client.post('/api/training/start',json=dict(self.payload,**changes)).status_code,422)
        self.assertFalse(list(self.queue.store.directory.glob('*/state.json')))
        identity='e'*32;data=dict(job_id=identity,character_id='actor',engine='cosyvoice',model_name='legacy',stored_filename='x.wav',transcript_filename='x.json',status='queued',progress=0,current_step='old',created_at='2020',updated_at='2020')
        path=self.fixture.jobs/(identity+'.json');path.write_text(json.dumps(data),encoding='utf8');before=path.read_bytes()
        self.assertEqual(self.client.get('/api/training/'+identity).json()['engine'],'cosyvoice')
        self.assertEqual(self.client.post('/api/training/'+identity+'/cancel').status_code,409)
        self.assertEqual(self.client.get('/api/training').status_code,200)
        self.assertTrue(any(item['code']=='legacy_pending_not_resumed' for item in self.client.get('/api/training/diagnostics').json()))
        self.assertEqual(path.read_bytes(),before)
    def test_other_backend_features_do_not_initialize_training_storage(self):
        from app import app
        manager=Mock();manager.list.return_value=[]
        with patch.object(training,'_queue',None),patch.object(training,'TrainingQueue',return_value=manager) as factory,TestClient(app) as client:
            self.assertEqual(client.get('/health').status_code,200)
            factory.assert_not_called()
            self.assertEqual(client.get('/api/training').json(),[])
            factory.assert_called_once()
        manager.close.assert_called_once()

if __name__=='__main__':unittest.main()
