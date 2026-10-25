"""Owned suspended worker failure injection and actual Windows lifecycle."""
import os
from pathlib import Path
import sys
import tempfile
import time
import unittest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'backend'))
from services.owned_worker import OwnedWorker, OwnershipError, WinAPI

class FakeAPI:
    def __init__(self,fail=None,stuck=False):
        self.fail=fail;self.stuck=stuck;self.events=[];self.alive=False;self.closed=[]
    def event(self,name):
        self.events.append(name)
        if self.fail==name:raise OSError('injected')
    def create_job(self):self.event('create_job');return 'job'
    def configure(self,job):self.event('configure')
    def create_process(self,command,cwd):self.event('create_process');self.alive=True;return 'process','thread'
    def assign(self,job,process):self.event('assign')
    def resume(self,thread):self.event('resume')
    def poll(self,process):return None if self.alive else 0
    def terminate_job(self,job):
        self.event('terminate_job')
        if not self.stuck:self.alive=False
    def terminate_process(self,process):
        self.event('terminate_process')
        if not self.stuck:self.alive=False
    def wait(self,process,timeout):return not self.alive
    def close(self,handle):self.closed.append(handle)

class OwnershipTests(unittest.TestCase):
    def test_assign_before_resume_and_close_is_idempotent(self):
        api=FakeAPI();worker=OwnedWorker(api=api)
        worker.start([sys.executable,'-c','pass'])
        self.assertLess(api.events.index('assign'),api.events.index('resume'))
        self.assertIsNone(worker.poll());worker.stop();worker.close();worker.close()
        self.assertFalse(api.alive);self.assertCountEqual(api.closed,['thread','process','job'])
    def test_fail_closed_at_every_launch_step(self):
        for step in ('create_job','configure','create_process','assign','resume'):
            api=FakeAPI(step);worker=OwnedWorker(api=api)
            with self.assertRaises(OwnershipError):worker.start([sys.executable,'-c','pass'])
            self.assertFalse(api.alive,step)
            if step=='assign':self.assertNotIn('resume',api.events)
            self.assertFalse(worker.owned)
    def test_failed_cleanup_keeps_ownership_and_can_retry(self):
        api=FakeAPI('assign',stuck=True);worker=OwnedWorker(api=api)
        with self.assertRaises(OwnershipError):worker.start([sys.executable,'-c','pass'])
        self.assertTrue(worker.owned);self.assertNotIn('process',api.closed)
        with self.assertRaises(OwnershipError):worker.close()
        api.stuck=False;worker.stop();self.assertFalse(worker.owned)

@unittest.skipUnless(os.name=='nt','Windows-only owned jobs')
class NativeOwnershipTests(unittest.TestCase):
    def test_real_child_exit_stop_and_assignment_failure(self):
        with tempfile.TemporaryDirectory() as directory:
            marker=Path(directory)/'ran'
            command=[sys.executable,'-c',f'from pathlib import Path;Path({str(marker)!r}).write_text("ran");import time;time.sleep(30)']
            class Denied(WinAPI):
                def assign(self,*args):raise OSError('denied')
            failed=OwnedWorker(api=Denied())
            with self.assertRaises(OwnershipError):failed.start(command)
            self.assertFalse(marker.exists());self.assertFalse(failed.owned)
            worker=OwnedWorker();self.addCleanup(worker.close);worker.start(command)
            deadline=time.monotonic()+5
            while not marker.exists() and time.monotonic()<deadline:time.sleep(.01)
            self.assertTrue(marker.exists());worker.stop();self.assertFalse(worker.owned)
            worker.start([sys.executable,'-c','pass'])
            deadline=time.monotonic()+5
            while worker.poll() is None and time.monotonic()<deadline:time.sleep(.01)
            self.assertEqual(worker.poll(),0);worker.close()
    def test_nested_job_inside_owned_child(self):
        backend=str(Path(__file__).resolve().parents[1]/'backend')
        script=f'import sys;sys.path.insert(0,{backend!r});from services.owned_worker import OwnedWorker;w=OwnedWorker();w.start([sys.executable,"-c","import time;time.sleep(30)"]);w.stop()'
        worker=OwnedWorker();self.addCleanup(worker.close);worker.start([sys.executable,'-c',script])
        deadline=time.monotonic()+8
        while worker.poll() is None and time.monotonic()<deadline:time.sleep(.01)
        self.assertEqual(worker.poll(),0);worker.close()

    def test_parent_crash_closes_job_and_stops_descendant(self):
        backend=str(Path(__file__).resolve().parents[1]/'backend')
        with tempfile.TemporaryDirectory() as directory:
            marker=Path(directory)/'heartbeat'
            child=f'from pathlib import Path;import time;p=Path({str(marker)!r});\nwhile True:p.write_text(str(time.time()));time.sleep(.02)'
            parent=f'import sys,time,os;sys.path.insert(0,{backend!r});from services.owned_worker import OwnedWorker;w=OwnedWorker();w.start([sys.executable,"-c",{child!r}]);time.sleep(.4);os._exit(7)'
            worker=OwnedWorker();self.addCleanup(worker.close);worker.start([sys.executable,'-c',parent])
            deadline=time.monotonic()+5
            while worker.poll() is None and time.monotonic()<deadline:time.sleep(.01)
            self.assertEqual(worker.poll(),7);self.assertTrue(marker.exists())
            first=marker.read_bytes();time.sleep(.2);self.assertEqual(marker.read_bytes(),first)
            worker.close()

if __name__=='__main__':unittest.main()
