import ctypes as c
from ctypes import wintypes as w
import json,subprocess,sys
k=c.WinDLL('kernel32',use_last_error=True)
class Basic(c.Structure):
 _fields_=[('process_time',c.c_int64),('job_time',c.c_int64),('flags',w.DWORD),('min_working',c.c_size_t),('max_working',c.c_size_t),('active',w.DWORD),('affinity',c.c_size_t),('priority',w.DWORD),('scheduling',w.DWORD)]
class IO(c.Structure):
 _fields_=[(name,c.c_uint64) for name in ('read_ops','write_ops','other_ops','read_bytes','write_bytes','other_bytes')]
class Extended(c.Structure):
 _fields_=[('basic',Basic),('io',IO),('process_memory',c.c_size_t),('job_memory',c.c_size_t),('peak_process',c.c_size_t),('peak_job',c.c_size_t)]
class Startup(c.Structure):
 _fields_=[('cb',w.DWORD),('reserved',w.LPWSTR),('desktop',w.LPWSTR),('title',w.LPWSTR),('x',w.DWORD),('y',w.DWORD),('width',w.DWORD),('height',w.DWORD),('charsx',w.DWORD),('charsy',w.DWORD),('fill',w.DWORD),('flags',w.DWORD),('show',w.WORD),('reserved2size',w.WORD),('reserved2',c.c_void_p),('stdin',w.HANDLE),('stdout',w.HANDLE),('stderr',w.HANDLE)]
class Process(c.Structure):
 _fields_=[('process',w.HANDLE),('thread',w.HANDLE),('pid',w.DWORD),('tid',w.DWORD)]
k.CreateJobObjectW.argtypes=[c.c_void_p,w.LPCWSTR];k.CreateJobObjectW.restype=w.HANDLE
k.SetInformationJobObject.argtypes=[w.HANDLE,c.c_int,c.c_void_p,w.DWORD];k.SetInformationJobObject.restype=w.BOOL
k.CreateProcessW.argtypes=[w.LPCWSTR,w.LPWSTR,c.c_void_p,c.c_void_p,w.BOOL,w.DWORD,c.c_void_p,w.LPCWSTR,c.POINTER(Startup),c.POINTER(Process)];k.CreateProcessW.restype=w.BOOL
k.AssignProcessToJobObject.argtypes=[w.HANDLE,w.HANDLE];k.AssignProcessToJobObject.restype=w.BOOL
k.ResumeThread.argtypes=[w.HANDLE];k.ResumeThread.restype=w.DWORD
k.WaitForSingleObject.argtypes=[w.HANDLE,w.DWORD];k.WaitForSingleObject.restype=w.DWORD
k.TerminateProcess.argtypes=[w.HANDLE,w.UINT];k.TerminateProcess.restype=w.BOOL
k.CloseHandle.argtypes=[w.HANDLE];k.CloseHandle.restype=w.BOOL
job=None;process=Process()
def check(value):
 if not value:raise c.WinError(c.get_last_error())
try:
 job=k.CreateJobObjectW(None,None);check(job)
 info=Extended();info.basic.flags=0x2000
 check(k.SetInformationJobObject(job,9,c.byref(info),c.sizeof(info)))
 startup=Startup();startup.cb=c.sizeof(startup)
 command=c.create_unicode_buffer(subprocess.list2cmdline([sys.executable,'-c','import time; time.sleep(30)']))
 check(k.CreateProcessW(sys.executable,command,None,None,False,0x08000000|4,None,None,c.byref(startup),c.byref(process)))
 check(k.AssignProcessToJobObject(job,process.process))
 if k.ResumeThread(process.thread)==0xffffffff:raise c.WinError(c.get_last_error())
 assert k.WaitForSingleObject(process.process,50)==258,'Child did not remain alive before job close'
 check(k.CloseHandle(job));job=None
 assert k.WaitForSingleObject(process.process,5000)==0,'Owned child did not exit after job close'
 print(json.dumps(dict(status='PASS',python=sys.version.split()[0],suspended_create=True,assigned_before_resume=True,kill_on_job_close=True,owned_child_reaped=True,model_loaded=False)))
finally:
 if process.process:
  if k.WaitForSingleObject(process.process,0)!=0:
   k.TerminateProcess(process.process,1);k.WaitForSingleObject(process.process,5000)
  k.CloseHandle(process.process)
 if process.thread:k.CloseHandle(process.thread)
 if job:k.CloseHandle(job)
