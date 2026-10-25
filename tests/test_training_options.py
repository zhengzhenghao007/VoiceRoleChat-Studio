"""Strict bounded training options, preserved defaults and final checkpoint mapping."""
import json,sys,unittest
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'backend'))
from pydantic import ValidationError
from schemas.training import TrainingOptions,TrainingRequest
from workers import training_worker as worker
import test_training_pipeline as fixtures

class TrainingOptionTests(unittest.TestCase):
    def setUp(self):
        self.fixture=fixtures.TrainingPipelineTests();self.fixture.setUp();self.addCleanup(self.fixture.doCleanups)
    def test_defaults_and_strict_bounds(self):
        self.assertEqual(TrainingOptions().model_dump(),dict(sovits_epochs=8,gpt_epochs=15,batch_size=2))
        for options in [dict(batch_size=0),dict(batch_size=9),dict(batch_size=True),dict(batch_size='1'),dict(gpt_epochs=0),dict(gpt_epochs=101),dict(sovits_epochs=1.0),dict(unknown=1)]:
            with self.subTest(options=options),self.assertRaises(ValidationError):TrainingOptions(**options)
    def test_worker_config_options_and_final_checkpoint(self):
        f=self.fixture
        for epochs in (1,7):
            options=TrainingOptions(sovits_epochs=epochs,gpt_epochs=epochs,batch_size=1)
            with patch.object(worker,'GPT_SOVITS_ROOT',f.upstream),patch.object(worker,'run_command'):
                worker.train_sovits('fixture',f.experiment,f.work,f.work/'log',options=options)
                worker.train_gpt('fixture',f.experiment,f.work,f.work/'log',options=options)
            import yaml
            s2=json.loads((f.work/'s2_config.json').read_bytes());s1=yaml.safe_load((f.work/'s1_config.yaml').read_text(encoding='utf8'))
            self.assertEqual(s2['train']['epochs'],epochs);self.assertEqual(s1['train']['epochs'],epochs)
            self.assertEqual((s2['train']['batch_size'],s1['train']['batch_size']),(1,1))
            self.assertEqual(epochs%s2['train']['save_every_epoch'],0);self.assertEqual(epochs%s1['train']['save_every_n_epoch'],0)
    def test_persist_options_and_old_schema1_request_defaults(self):
        store=self.fixture.fixture.store
        request=TrainingRequest(character_id='actor',model_name='bounded',dataset_name='prepared',training_options=TrainingOptions(sovits_epochs=1,gpt_epochs=1,batch_size=1))
        job=store.create(request);protocol=store.request(job)
        self.assertEqual(protocol.request.training_options.batch_size,1);self.assertEqual(job['training_options']['gpt_epochs'],1)
        original=store.create(TrainingRequest(character_id='actor',model_name='old',dataset_name='prepared'))
        folder=store.folder(original['job_id']);data=json.loads((folder/'request.json').read_bytes());data['request'].pop('training_options')
        raw=json.dumps(data).encode('utf8');(folder/'request.json').write_bytes(raw)
        import hashlib
        original.pop('training_options');original['request_sha256']=hashlib.sha256(raw).hexdigest();store.persist(original)
        restored=store.load(original['job_id']);self.assertEqual(store.request(restored).request.training_options,TrainingOptions())
        self.assertEqual((folder/'request.json').read_bytes(),raw)
    def test_windows_conda_dll_paths_use_interpreter_prefix(self):
        prefix=self.fixture.root/'conda-env';python=prefix/'python.exe'
        with patch.object(worker,'GPT_SOVITS_PYTHON',python):environment=worker.create_process_environment()
        import os
        self.assertEqual(environment['PATH'].split(os.pathsep)[:2],[str(prefix/'Library/bin'),str(prefix/'DLLs')])

if __name__=='__main__':unittest.main()
