"""Windows suspended child ownership; no persisted PID takeover or shell."""
import os
import subprocess
from threading import RLock

class OwnershipError(RuntimeError):
    pass

class WinAPI:
    def __init__(self):
        if os.name != 'nt':
            raise OwnershipError('Safe background process ownership is unavailable on this platform')
        from services import _win32_job
        self.n = _win32_job
    def check(self, value):
        if not value: raise self.n.c.WinError(self.n.c.get_last_error())
        return value
    def create_job(self): return self.check(self.n.k.CreateJobObjectW(None,None))
    def configure(self, job):
        n=self.n; limits=n.Extended();limits.basic.flags=0x2000
        self.check(n.k.SetInformationJobObject(job,9,n.c.byref(limits),n.c.sizeof(limits)))
    def create_process(self, command, cwd):
        n=self.n; startup=n.Startup();startup.cb=n.c.sizeof(startup);process=n.Process()
        line=n.c.create_unicode_buffer(subprocess.list2cmdline(command))
        self.check(n.k.CreateProcessW(command[0],line,None,None,False,0x08000000|4,None,
            str(cwd) if cwd else None,n.c.byref(startup),n.c.byref(process)))
        return process.process,process.thread
    def assign(self, job, process): self.check(self.n.k.AssignProcessToJobObject(job,process))
    def resume(self, thread):
        if self.n.k.ResumeThread(thread)==0xffffffff:
            raise self.n.c.WinError(self.n.c.get_last_error())
    def poll(self, process):
        n=self.n; result=n.k.WaitForSingleObject(process,0)
        if result==258:return None
        if result!=0:raise n.c.WinError(n.c.get_last_error())
        code=n.w.DWORD();self.check(n.k.GetExitCodeProcess(process,n.c.byref(code)))
        return code.value
    def wait(self, process, timeout):
        result=self.n.k.WaitForSingleObject(process,int(timeout*1000))
        if result==258:return False
        if result!=0:raise self.n.c.WinError(self.n.c.get_last_error())
        return True
    def terminate_job(self, job):self.check(self.n.k.TerminateJobObject(job,1))
    def terminate_process(self, process):self.check(self.n.k.TerminateProcess(process,1))
    def close(self, handle):self.check(self.n.k.CloseHandle(handle))

class OwnedWorker:
    def __init__(self, *, api=None):
        self.api=api or WinAPI()
        self._job=self._process=self._thread=None
        self._bound=False;self._returncode=None;self._lock=RLock()
    @property
    def owned(self):return any(item is not None for item in (self._job,self._process,self._thread))
    def start(self, command, cwd=None):
        with self._lock:
            if self.owned:raise OwnershipError('An owned process has not been cleaned up')
            self._returncode=None;self._bound=False
            try:
                self._job=self.api.create_job();self.api.configure(self._job)
                self._process,self._thread=self.api.create_process(command,cwd)
                self.api.assign(self._job,self._process);self._bound=True
                self.api.resume(self._thread)
            except Exception as error:
                try:self.stop()
                except OwnershipError:pass  # Retain all live handles for retry by owner.
                raise OwnershipError('Safe worker launch failed; check platform process ownership') from error
    def poll(self):
        with self._lock:
            return self.api.poll(self._process) if self._process is not None else self._returncode
    def stop(self, timeout=2):
        with self._lock:
            try:
                if self._process is not None:
                    if self._bound:self.api.terminate_job(self._job)
                    elif self.api.poll(self._process) is None:self.api.terminate_process(self._process)
                    if not self.api.wait(self._process,timeout):
                        raise OwnershipError('Worker cleanup did not finish; ownership retained')
                    self._returncode=self.api.poll(self._process)
                for attribute in ('_thread','_process','_job'):
                    handle=getattr(self,attribute)
                    if handle is not None:
                        self.api.close(handle);setattr(self,attribute,None)
            except (OSError,OwnershipError) as error:
                raise OwnershipError('Worker cleanup failed; ownership retained') from error
    close=stop
