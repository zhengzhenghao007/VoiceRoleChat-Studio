"""Actual HTTP + outer/nested Windows jobs with six harmless fake upstream scripts."""
from contextlib import asynccontextmanager
from pathlib import Path
from threading import Thread
import hashlib,json,socket,sys,time,unittest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'backend'))
from fastapi import FastAPI
import httpx,uvicorn
from api import training
from services.training_queue import TrainingQueue
import test_training_queue_store as fixtures

class NativeTrainingTests(unittest.TestCase):
    def setUp(self):
        self.fixture=fixtures.TrainingStoreTests();self.fixture.setUp();self.addCleanup(self.fixture.doCleanups)
        f=self.fixture;self.upstream=Path(f.runtime['GPT_SOVITS_ROOT']);configs=self.upstream/'GPT_SoVITS/configs';configs.mkdir(parents=True)
        (configs/'s2v2Pro.json').write_text('{"train":{},"model":{},"data":{}}',encoding='utf8');(configs/'s1longer-v2.yaml').write_text('train: {}\n',encoding='utf8')
        scripts={
          'prepare_datasets/1-get-text.py':"import os\nfrom pathlib import Path\np=Path(os.environ['opt_dir']);(p/'2-name2text-0.txt').write_text('fixture\\tja\\ttext\\n')",
          'prepare_datasets/2-get-hubert-wav32k.py':"print('FAKE hubert, no model load')",
          'prepare_datasets/2-get-sv.py':"print('FAKE speaker, no model load')",
          'prepare_datasets/3-get-semantic.py':"import os\nfrom pathlib import Path\np=Path(os.environ['opt_dir']);(p/'6-name2semantic-0.tsv').write_text('item_name\\tsemantic_audio\\nfixture\\t1 2\\n')",
          's2_train.py':"import argparse,json\nfrom pathlib import Path\np=argparse.ArgumentParser();p.add_argument('--config');c=json.loads(Path(p.parse_args().config).read_bytes());o=Path(c['save_weight_dir']);o.mkdir(parents=True,exist_ok=True);(o/(c['name']+'_e1_s1.pth')).write_bytes(b'SIMULATED SOVITS NOT TRAINED')",
          's1_train.py':"import argparse,yaml\nfrom pathlib import Path\np=argparse.ArgumentParser();p.add_argument('--config_file');c=yaml.safe_load(Path(p.parse_args().config_file).read_text(encoding='utf8'));o=Path(c['train']['half_weights_save_dir']);o.mkdir(parents=True,exist_ok=True);(o/(c['train']['exp_name']+'-e1.ckpt')).write_bytes(b'SIMULATED GPT NOT TRAINED')"}
        for name,source in scripts.items():
            path=self.upstream/'GPT_SoVITS'/name;path.parent.mkdir(parents=True,exist_ok=True);path.write_text(source,encoding='utf8')
        self.queue=TrainingQueue(f.jobs,f.models,f.runtime,timeout=20);self.addCleanup(self.queue.close)
        app=FastAPI();app.include_router(training.router);app.dependency_overrides[training.get_training_queue]=lambda:self.queue
        self.socket=socket.socket();self.socket.bind(('127.0.0.1',0));self.socket.listen();self.port=self.socket.getsockname()[1]
        self.server=uvicorn.Server(uvicorn.Config(app,log_level='error',lifespan='off'));self.thread=Thread(target=self.server.run,kwargs={'sockets':[self.socket]},daemon=True);self.thread.start();self.addCleanup(self.stop_server)
        self.client=httpx.Client(base_url=f'http://127.0.0.1:{self.port}',timeout=10);self.addCleanup(self.client.close)
        deadline=time.monotonic()+5
        while not self.server.started and time.monotonic()<deadline:time.sleep(.02)
        self.assertTrue(self.server.started)
    def stop_server(self):
        self.server.should_exit=True;self.thread.join(5);self.socket.close()
    def submit(self):
        response=self.client.post('/api/training/start',json=self.fixture.request.model_dump(exclude_none=True));self.assertEqual(response.status_code,201,response.text)
        return response.json()['job_id']
    def wait(self,identity,states,timeout=20):
        deadline=time.monotonic()+timeout
        while time.monotonic()<deadline:
            response=self.client.get('/api/training/'+identity);self.assertEqual(response.status_code,200,response.text);job=response.json()
            if job['status'] in states:return job
            time.sleep(.04)
        self.fail('Training fixture deadline exceeded: '+repr(job))
    def heartbeat_pipeline(self):
        self.heartbeat=self.fixture.root/'heartbeat.txt';child=self.upstream/'harmless_descendant.py'
        child.write_text("from pathlib import Path\nimport time\np=Path("+repr(str(self.heartbeat))+")\nwhile True:\n p.write_text(str(time.time()))\n time.sleep(.04)\n",encoding='utf8')
        path=self.upstream/'GPT_SoVITS/prepare_datasets/1-get-text.py';path.write_text("import subprocess,sys,time\nsubprocess.Popen([sys.executable,"+repr(str(child))+"])\ntime.sleep(60)",encoding='utf8')
    def test_actual_http_fake_pipeline_atomically_commits_private_weights(self):
        identity=self.submit();job=self.wait(identity,{'completed','failed'})
        self.assertEqual(job['status'],'completed',repr(job)+'; '+repr(self.queue.diagnostics()))
        target=self.fixture.models/identity;manifest=json.loads((target/'manifest.json').read_bytes())
        self.assertEqual(manifest['training_task']['job_id'],identity);self.assertTrue(self.queue.store.committed(self.queue.get(identity)))
        self.assertIn('SIMULATED',(target/'gpt_v2pro.ckpt').read_text());self.assertFalse((self.upstream/'GPT_weights_v2Pro').exists());self.assertFalse((self.upstream/'SoVITS_weights_v2Pro').exists());self.assertFalse((self.upstream/'logs').exists())
        self.assertEqual(self.client.post('/api/training/'+identity+'/cancel').json()['status'],'completed')
        from services.model_service import ModelService
        models=ModelService(self.fixture.root,self.upstream/'GPT_weights_v2Pro',self.upstream/'SoVITS_weights_v2Pro').list_models()
        self.assertEqual(len(models),1,'Committed fake model must be discoverable; private weights must stay invisible')
        self.assertEqual(models[0].status,'ready')
    def test_running_cancel_stops_outer_nested_and_descendant(self):
        self.heartbeat_pipeline();identity=self.submit();deadline=time.monotonic()+20
        while not self.heartbeat.exists() and time.monotonic()<deadline:
            if self.queue.get(identity)['status'] in ('failed','timed_out'):break
            time.sleep(.03)
        self.assertTrue(self.heartbeat.exists(),repr(self.queue.get(identity))+'; '+repr(self.queue.diagnostics())+'; '+repr((self.fixture.jobs/(identity+'.log')).read_text(encoding='utf8') if (self.fixture.jobs/(identity+'.log')).exists() else 'no log'))
        response=self.client.post('/api/training/'+identity+'/cancel');self.assertEqual(response.status_code,202)
        self.assertEqual(self.wait(identity,{'cancelled','failed'})['status'],'cancelled')
        before=self.heartbeat.read_bytes();time.sleep(.2);self.assertEqual(self.heartbeat.read_bytes(),before);self.assertFalse((self.fixture.models/identity).exists())
    def test_whole_task_timeout_stops_descendant_and_never_exports(self):
        self.heartbeat_pipeline();clock=[0.0];self.queue.clock=lambda:clock[0];self.queue.timeout=4;identity=self.submit()
        deadline=time.monotonic()+20
        while not self.heartbeat.exists() and time.monotonic()<deadline:
            if self.queue.get(identity)['status']=='failed':break
            time.sleep(.03)
        self.assertTrue(self.heartbeat.exists(),repr(self.queue.get(identity)))
        clock[0]=4.01
        self.assertEqual(self.wait(identity,{'timed_out','failed'},timeout=5)['status'],'timed_out')
        self.assertTrue(self.heartbeat.exists());before=self.heartbeat.read_bytes();time.sleep(.2);self.assertEqual(self.heartbeat.read_bytes(),before)
        self.assertFalse((self.fixture.models/identity).exists())
    def test_legacy_http_request_uses_private_snapshots_and_exports(self):
        payload=dict(character_id='actor',model_name='legacy',stored_filename=self.fixture.fixture.source.name,transcript_filename='a'*32+'.json')
        response=self.client.post('/api/training/start',json=payload);self.assertEqual(response.status_code,201,response.text)
        identity=response.json()['job_id'];job=self.wait(identity,{'completed','failed'})
        self.assertEqual(job['status'],'completed',repr(job))
        provenance=json.loads((self.fixture.jobs/identity/'input-provenance.json').read_bytes())
        self.assertEqual(provenance['mode'],'legacy')
        self.assertEqual(sorted(path.name for path in self.fixture.fixture.service.root.iterdir()),['prepared'])

if __name__=='__main__':unittest.main()
