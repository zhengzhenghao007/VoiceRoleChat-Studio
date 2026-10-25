"""One parent-owned durable Windows training pipeline and bounded FIFO queue."""
import os,re,sys,time
from pathlib import Path
from threading import Event,RLock,Lock,Thread
from pydantic import ValidationError
from schemas.training_queue import Progress
from services.owned_worker import OwnedWorker,OwnershipError
from services.training_queue_store import TrainingStore,QueueError
from services.transcription_job_service import now,read_json,JobError,safe

TERMINAL={'completed','failed','cancelled','timed_out','interrupted'}

class RootLease:
    def __init__(self,path):
        self.handle=None
        if os.name!='nt':raise QueueError('Safe training supervision is available only on Windows')
        import msvcrt
        try:
            self.handle=safe(path).open('a+b');self.handle.seek(0)
            msvcrt.locking(self.handle.fileno(),msvcrt.LK_NBLCK,1)
            if self.handle.seek(0,2)==0:self.handle.write(b'0');self.handle.flush()
        except (OSError,JobError) as error:
            if self.handle:self.handle.close();self.handle=None
            raise QueueError('Another training supervisor owns this directory') from error
    def close(self):
        if self.handle:
            import msvcrt
            self.handle.seek(0);msvcrt.locking(self.handle.fileno(),msvcrt.LK_UNLCK,1);self.handle.close();self.handle=None

class TrainingQueue:
    def __init__(self,jobs,models,runtime,*,worker_factory=OwnedWorker,timeout=86400,autostart=True,clock=time.monotonic):
        if not 0<timeout<=604800:raise QueueError('Invalid training task timeout')
        self.store=TrainingStore(jobs,models,runtime);self.lease=RootLease(self.store.directory/'manager.lock')
        self.factory=worker_factory;self.timeout=timeout;self.clock=clock;self.lock=RLock();self.step_lock=Lock()
        self._jobs={};self._diagnostics=[];self._worker=None;self._active_id=None;self._started=0
        self._cleanup_pending=False;self._unavailable=False;self._closing=False;self._stop=Event();self._wake=Event();self._thread=None
        try:
            self._recover()
            self.store._sequence=max((job['enqueue_order'] for job in self._jobs.values()),default=0)
            if autostart:
                self._thread=Thread(target=self._loop,name='training-supervisor',daemon=True);self._thread.start()
        except Exception:self.lease.close();raise
    def _persist(self,data):
        checked=self.store.persist(data);self._jobs[checked['job_id']]=checked;return dict(checked)
    def _change(self,job,**values):return dict(job,**values,updated_at=now())
    def _diagnose(self,identity,code):
        item=dict(job_id=identity,code=code)
        if item not in self._diagnostics:self._diagnostics.append(item)
    def _completed(self,job):
        result=self._change(job,status='completed',progress=100,current_step='Training completed',decision=None,error=None,error_code=None,model_path='models/'+job['job_id'])
        try:return self._persist(result)
        except QueueError:
            result['error_code']='state_write_failed';self._jobs[job['job_id']]=result;self._unavailable=True
            return dict(result)
    def _recover(self):
        for folder in self.store.directory.iterdir():
            if not re.fullmatch(r'[0-9a-f]{32}',folder.name):continue
            try:
                job=self.store.load(folder.name);self.store.request(job);self._jobs[folder.name]=job
                if self.store.committed(job):self._completed(job)
                elif job['status'] not in TERMINAL:
                    status=job['decision'] or 'interrupted'
                    self._persist(self._change(job,status=status,current_step='Recovered without rerunning',error_code='backend_restarted',error=None))
                elif job['status']=='completed':
                    self._persist(self._change(job,status='interrupted',progress=min(job['progress'],99),model_path=None,error_code='committed_model_unavailable'))
                    self._diagnose(folder.name,'committed_model_unavailable')
            except (QueueError,OSError,ValueError,JobError):
                self._jobs.pop(folder.name,None);self._diagnose(folder.name,'invalid_or_future_record')
    def submit(self,request):
        with self.lock:
            if self._closing or self._cleanup_pending or self._unavailable:raise QueueError('Training queue unavailable; cleanup or storage needs attention')
            if sum(job['status']=='queued' for job in self._jobs.values())>=5:raise QueueError('Training queue is full',429)
            try:
                capability=self.factory();capability.close()
            except OwnershipError as error:raise QueueError('Safe training process ownership unavailable') from error
            job=self.store.create(request);self._jobs[job['job_id']]=job
            self._wake.set();return dict(job)
    def get(self,identity):
        self.store.folder(identity)
        with self.lock:
            if identity in self._jobs:return dict(self._jobs[identity])
            if self.store.folder(identity).exists():raise QueueError('Training record is invalid or unavailable',404)
            return self.store.legacy(identity)
    def list(self):
        with self.lock:
            items=[dict(job) for job in self._jobs.values()]
            for path in self.store.jobs.glob('*.json'):
                if not re.fullmatch(r'[0-9a-f]{32}\.json',path.name):continue
                if path.stem in self._jobs:continue
                try:
                    job=self.store.legacy(path.stem);items.append(job)
                    if job['status'] not in TERMINAL:self._diagnose(path.stem,'legacy_pending_not_resumed')
                except QueueError:self._diagnose(path.stem,'invalid_or_future_legacy_record')
            return sorted(items,key=lambda job:(job['created_at'],job['job_id']),reverse=True)
    def diagnostics(self):
        self.list()
        with self.lock:return list(self._diagnostics)
    def cancel(self,identity):
        with self.lock:
            job=self.get(identity)
            if job.get('schema_version',0)!=1:raise QueueError('Legacy records are read-only; create a new task to retry',409)
            if job['status'] in TERMINAL:return job
            if job['decision'] is None:
                values=dict(decision='cancelled',current_step='Cancellation requested')
                if job['status']=='queued':values.update(status='cancelled',current_step='Cancelled before launch')
                job=self._persist(self._change(job,**values))
            self._wake.set();return job
    def _decision(self,job):
        if job['decision']:return job
        decision='interrupted' if self._closing else ('timed_out' if self.clock()-self._started>=self.timeout else None)
        return self._persist(self._change(job,decision=decision,current_step='Stopping owned training process')) if decision else job
    def _reap(self,job):
        if self._worker is None:return True
        try:self._worker.close()
        except OwnershipError:
            self._cleanup_pending=True
            try:self._persist(self._change(job,error_code='cleanup_pending',current_step='Process cleanup pending; next task blocked'))
            except QueueError:self._unavailable=True
            return False
        self._worker=None;self._cleanup_pending=False;return True
    def _finish_decision(self,job):
        if not self._reap(job):return
        self._persist(self._change(job,status=job['decision'],current_step='Training stopped',error_code=job['decision'],error=None,model_path=None))
        self._active_id=None
    def _progress(self,job):
        path=self.store.folder(job['job_id'])/'progress.json'
        if not path.exists():return job
        try:
            data=Progress.model_validate(read_json(path,8192),strict=True)
            if any(getattr(data,key)!=job[key] for key in ('job_id','run_nonce','request_sha256')):raise ValueError('Progress identity')
            if data.sequence<=job['progress_seq']:return job
            return self._persist(self._change(job,progress=max(job['progress'],data.progress),current_step=data.current_step,status='training' if data.status=='training' else job['status'],progress_seq=data.sequence,error_code=data.error_code))
        except (JobError,ValueError,ValidationError):self._diagnose(job['job_id'],'invalid_progress');return job
    def tick(self):
        with self.step_lock:
            try:self._tick()
            except (QueueError,OSError,JobError):
                with self.lock:
                    self._unavailable=True
                    if self._active_id is not None and (self._closing or self.clock()-self._started>=self.timeout):
                        # No terminal acknowledgement without durable state, but the
                        # actual work budget must still stop the owned process.
                        self._reap(self._jobs[self._active_id])
                        self._diagnose(self._active_id,'state_storage_failed_at_deadline')
                raise
    def _tick(self):
        with self.lock:
            if self._active_id is None:
                if self._closing or self._unavailable:return
                queued=[job for job in self._jobs.values() if job['status']=='queued']
                if not queued:return
                job=min(queued,key=lambda job:(job['enqueue_order'],job['created_at'],job['job_id']))
                try:
                    request=self.store.request(job);self.store.verify_inputs(request)
                except QueueError:
                    self._persist(self._change(job,status='failed',error_code='input_changed',error='Training source is unavailable or changed'));return
                job=self._persist(self._change(job,status='preparing',current_step='Starting owned training pipeline'))
                self._active_id=job['job_id'];self._started=self.clock()
                try:
                    self._worker=self.factory()
                    self._worker.start([sys.executable,str(Path(__file__).resolve().parents[1]/'workers/training_queue_worker.py'),str(self.store.folder(job['job_id'])/'request.json')],cwd=self.store.runtime.GPT_SOVITS_ROOT)
                except (OwnershipError,OSError):
                    if self._reap(job):
                        self._persist(self._change(job,status='failed',error_code='ownership_failed'));self._active_id=None
                return
            job=self._jobs[self._active_id];job=self._decision(job)
            if job['decision']:self._finish_decision(job);return
            job=self._progress(job)
            try:code=self._worker.poll() if self._worker else 0
            except (OwnershipError,OSError):code=1
            if code is None:return
            if not self._reap(job):return
            job=self._progress(self._jobs[job['job_id']])
            if code!=0:
                self._persist(self._change(job,status='failed',error_code=job['error_code'] or 'pipeline_failed',error='Training pipeline did not produce a committed model'));self._active_id=None;return
        # Bounded large-file hashes happen outside the state lock, so cancel can persist.
        try:prepared=self.store.validate_export(job)
        except QueueError:
            with self.lock:
                fresh=self._decision(self._jobs[job['job_id']])
                if fresh['decision']:self._finish_decision(fresh)
                else:
                    self._persist(self._change(fresh,status='failed',error_code='invalid_candidate'));self._active_id=None
            return
        with self.lock:
            fresh=self._decision(self._jobs[job['job_id']])
            if fresh['decision']:self._finish_decision(fresh);return
            try:self.store.publish(fresh,prepared)
            except QueueError:
                self._persist(self._change(fresh,status='failed',error_code='publication_failed'));self._active_id=None;return
            self._completed(fresh);self._active_id=None
    def _loop(self):
        while not self._stop.is_set():
            try:self.tick()
            except (QueueError,OSError,JobError):
                with self.lock:self._unavailable=True
            self._wake.wait(.05);self._wake.clear()
    def close(self):
        persistence_error=None
        with self.lock:
            self._closing=True
            for job in list(self._jobs.values()):
                if job['status'] not in TERMINAL and job['decision'] is None:
                    values=dict(decision='interrupted',current_step='Backend shutting down')
                    if job['status']=='queued':values['status']='interrupted'
                    try:self._persist(self._change(job,**values))
                    except QueueError as error:persistence_error=error;self._unavailable=True
            self._stop.set();self._wake.set()
        if self._thread and self._thread.is_alive():self._thread.join(3)
        if self._thread and self._thread.is_alive():raise QueueError('Training supervisor shutdown still pending; ownership retained')
        if persistence_error:
            # Shutdown must still reap owned processes if the intent cannot be saved.
            # No terminal outcome is acknowledged; restart will reconcile old state.
            with self.step_lock,self.lock:
                if self._worker is not None:
                    job=self._jobs[self._active_id]
                    if not self._reap(job):raise QueueError('Training cleanup pending after state storage failure')
                self._active_id=None
                self.lease.close()
            raise QueueError('Training process reaped but shutdown state could not be saved') from persistence_error
        self.tick()
        with self.lock:
            if self._worker is not None or self._cleanup_pending:raise QueueError('Training process cleanup pending; ownership retained')
            self.lease.close()
