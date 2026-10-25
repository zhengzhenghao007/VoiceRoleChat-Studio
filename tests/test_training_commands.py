"""Harmless native command fixtures; no upstream training or ML."""
from pathlib import Path
from threading import Event,Thread
import json,os,sys,tempfile,time,unittest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'backend'))
from services.training_command import TrainingCommands,CommandError

class TrainingCommandTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup);self.root=Path(self.temp.name)
        self.upstream=self.root/'upstream';self.jobs=self.root/'jobs';self.jobs.mkdir()
        self.script=self.upstream/'GPT_SoVITS/prepare_datasets/1-get-text.py';self.script.parent.mkdir(parents=True)
        self.log=self.jobs/('a'*32+'.log');self.log.touch()
        self.runner=TrainingCommands(self.upstream,self.jobs,python=sys.executable,timeout=4);self.addCleanup(self.runner.close)
    def run_step(self,**kwargs):return self.runner.run('text',environment=dict(os.environ),log_path=self.log,**kwargs)
    def test_success_nonzero_logs_and_environment(self):
        self.script.write_text("import os,sys\nprint('out:'+os.environ.get('exp_name',''))\nprint('err',file=sys.stderr)",encoding='utf8')
        environment=dict(os.environ,exp_name='fixture')
        self.runner.run('text',environment=environment,log_path=self.log)
        self.assertIn('out:fixture',self.log.read_text());self.assertIn('err',self.log.read_text())
        request=json.loads(next((self.jobs/'.commands').glob('*/request.json')).read_bytes())
        self.assertEqual(request['environment'],{'exp_name':'fixture'});self.assertNotIn('PATH',request['environment'])
        self.script.write_text('raise SystemExit(7)',encoding='utf8')
        with self.assertRaises(CommandError) as error:self.run_step()
        self.assertEqual(error.exception.code,'exit_nonzero')
    def test_unknown_env_and_step_rejected(self):
        with self.assertRaises(CommandError):self.runner.run('text',environment=dict(os.environ,UNEXPECTED_SECRET='never persist'),log_path=self.log)
        with self.assertRaises(CommandError):self.runner.run('arbitrary',environment=dict(os.environ),log_path=self.log)
        self.assertFalse((self.jobs/'.commands').exists())
    def test_timeout_kills_descendant_heartbeat(self):
        heartbeat=self.root/'heartbeat';descendant=self.root/'descendant.py'
        descendant.write_text("import time\nfrom pathlib import Path\np=Path("+repr(str(heartbeat))+ ")\nwhile True:\n p.write_text(str(time.time()))\n time.sleep(.04)\n",encoding='utf8')
        self.script.write_text("import subprocess,sys,time\nsubprocess.Popen([sys.executable,"+repr(str(descendant))+"])\ntime.sleep(30)",encoding='utf8')
        self.runner.timeout=1.5
        with self.assertRaises(CommandError) as error:self.run_step()
        self.assertEqual(error.exception.code,'timed_out');self.assertTrue(heartbeat.exists())
        before=heartbeat.read_bytes();time.sleep(.2);self.assertEqual(heartbeat.read_bytes(),before)
    def test_cancel_and_shutdown_reject_new_commands(self):
        self.script.write_text('import time\ntime.sleep(30)',encoding='utf8');cancel=Event();errors=[]
        def running():
            try:self.run_step(cancel=cancel)
            except CommandError as error:errors.append(error.code)
        thread=Thread(target=running);thread.start();time.sleep(.3);cancel.set();thread.join(5)
        self.assertFalse(thread.is_alive());self.assertEqual(errors,['cancelled'])
        self.runner.close()
        with self.assertRaises(CommandError) as error:self.run_step()
        self.assertEqual(error.exception.code,'closed')
    def test_missing_log_and_path_escape_rejected(self):
        self.script.write_text('pass',encoding='utf8')
        for log in [self.jobs/('b'*32+'.log'),self.root/'outside.log']:
            with self.assertRaises(CommandError):self.runner.run('text',environment=dict(os.environ),log_path=log)
    def test_cleanup_failure_retains_owner_blocks_next_command(self):
        class Owner:
            owned=True;fail=True
            def start(self,*args,**kwargs):pass
            def poll(self):return 0
            def close(self):
                from services.owned_worker import OwnershipError
                if self.fail:raise OwnershipError('retained')
                self.owned=False
        owner=Owner();self.runner.factory=lambda:owner;self.script.write_text('pass',encoding='utf8')
        with self.assertRaises(CommandError) as error:self.run_step()
        self.assertEqual(error.exception.code,'cleanup_failed')
        with self.assertRaises(CommandError):self.run_step()
        owner.fail=False;self.runner.retry_cleanup();self.assertFalse(owner.owned)

    def test_shutdown_active_command_and_rejects_admission(self):
        self.script.write_text('import time\ntime.sleep(30)',encoding='utf8');errors=[]
        def running():
            try:self.run_step()
            except CommandError as error:errors.append(error.code)
        thread=Thread(target=running);thread.start();time.sleep(.3);self.runner.close();thread.join(5)
        self.assertFalse(thread.is_alive());self.assertEqual(errors,['closed'])
        with self.assertRaises(CommandError):self.run_step()
    def test_six_step_contract_and_path_prefix(self):
        from services.training_command import validate_request,STEPS,environment_delta
        work=self.jobs/self.log.stem;work.mkdir();(work/'s2_config.json').write_text('{}');(work/'s1_config.yaml').write_text('x: 1')
        for step,script in STEPS.items():
            data=dict(version=1,step=step,python=sys.executable,upstream=str(self.upstream),jobs=str(self.jobs),log=str(self.log),environment={},path_prefix=[])
            command=validate_request(data);self.assertEqual(command[:3],[sys.executable,'-s',script])
            self.assertEqual(len(command),5 if step in ('sovits','gpt') else 3)
            if step=='gpt':self.assertEqual(command[3],'--config_file')
        prefix=self.root/'bin';prefix.mkdir();environment=dict(os.environ);environment['PATH']=str(prefix)+os.pathsep+os.environ['PATH']
        changes,parts=environment_delta(environment);self.assertEqual(parts,[str(prefix)]);self.assertNotIn('PATH',changes)
    def test_launch_failure_never_reports_success(self):
        from services.owned_worker import OwnershipError
        class Owner:
            def start(self,*args,**kwargs):raise OwnershipError('fail before execution')
            def close(self):pass
        self.runner.factory=Owner
        with self.assertRaises(CommandError) as error:self.run_step()
        self.assertEqual(error.exception.code,'ownership_failed')

if __name__=='__main__':unittest.main()
