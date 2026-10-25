"""Single owned offline transcription worker with durable intents and commits."""
from datetime import datetime,timezone
import hashlib,json,logging,os,re,sys,tempfile,time
from pathlib import Path
from threading import Event,RLock,Thread
from uuid import uuid4
from pydantic import ValidationError
from faster_whisper.tokenizer import _LANGUAGE_CODES
from services.audio_service import AudioService,AudioError
from services.owned_worker import OwnedWorker,OwnershipError
from schemas.transcription_job import JobRecord,WorkerRequest,Candidate,TranscriptRecord

MAX_RESULT=8*1024*1024
TERMINAL={'succeeded','failed','cancelled','timed_out','interrupted'}
logger=logging.getLogger(__name__)
class JobError(RuntimeError):
    def __init__(self,message,status_code=503):super().__init__(message);self.status_code=status_code

def now():return datetime.now(timezone.utc).isoformat()
def safe(path):
    try:
        path=Path(path).absolute()
        resolved=path.resolve()
    except (OSError,RuntimeError) as error:
        raise JobError('Unsafe or unresolvable storage path') from error
    if resolved!=path:raise JobError('Unsafe job storage path')
    return path

def read_json(path,limit=MAX_RESULT):
    try:
        with safe(path).open('rb') as handle:data=handle.read(limit+1)
        if len(data)>limit:raise ValueError('Large JSON')
        return json.loads(data)
    except (OSError,ValueError,RecursionError) as error:
        raise JobError('Job metadata or worker output is unavailable or invalid') from error

def atomic_json(path,data,limit=MAX_RESULT):
    temporary=None
    try:
        path=safe(path)
        encoded=json.dumps(data,ensure_ascii=False,allow_nan=False).encode('utf8')
        if len(encoded)>limit:raise ValueError('Large JSON')
        with tempfile.NamedTemporaryFile(dir=safe(path.parent),suffix='.tmp',delete=False) as handle:
            temporary=Path(handle.name);handle.write(encoded);handle.flush();os.fsync(handle.fileno())
        os.replace(temporary,safe(path))
    except (OSError,ValueError) as error:raise JobError('Job data could not be published') from error
    finally:
        if temporary is not None:
            try:temporary.unlink(missing_ok=True)
            except OSError:logger.error('Job staging cleanup failed')

class TranscriptionJobs:
    def __init__(self,root,uploads,*,worker_factory=OwnedWorker,timeout=300,autostart=True):
        self.root=Path(root).resolve();self.uploads=Path(uploads).resolve()
        self.root.mkdir(parents=True,exist_ok=True)
        self.directory=safe(self.root/'.jobs');self.directory.mkdir(exist_ok=True)
        self.factory=worker_factory;self.timeout=timeout
        self._lock=RLock();self._stop=Event();self._wake=Event();self._thread=None
        self._jobs={};self._diagnostics=[];self._worker=None;self._active_id=None
        self._started=0;self._closing=False;self._unavailable=False
        self._recover()
        if autostart:
            self._thread=Thread(target=self._loop,name='transcription-jobs',daemon=True);self._thread.start()
    def _folder(self,identity):
        if not re.fullmatch(r'[0-9a-f]{32}',identity):raise JobError('Transcription job not found',404)
        return safe(self.directory/identity)
    def _persist(self,data):
        checked=JobRecord.model_validate(data,strict=True).model_dump()
        atomic_json(self._folder(checked['id'])/'state.json',checked,16384)
        self._jobs[checked['id']]=checked
        return dict(checked)
    def _change(self,data,**values):return dict(data,**values,updated_at=now())
    def _result(self,job):
        try:
            result=TranscriptRecord.model_validate(read_json(safe(self.root/(job['id']+'.json'))),strict=True)
            if (result.task_id!=job['id'] or result.run_nonce!=job['run_nonce'] or result.source_sha256!=job['source_sha256']
                    or result.stored_filename!=job['source_filename'] or result.language not in _LANGUAGE_CODES):return None
            return result
        except (JobError,ValidationError):return None
    def _success(self,job):
        done=self._change(job,state='succeeded',phase='finished',result_id=job['id'],
            transcript_file='transcripts/'+job['id']+'.json',error_code=None)
        try:return self._persist(done)
        except JobError:
            # Result replacement is the commit; cancellation cannot undo it.
            done['error_code']='state_write_failed';self._jobs[job['id']]=done
            return dict(done)
    def _recover(self):
        for folder in self.directory.iterdir():
            if not re.fullmatch(r'[0-9a-f]{32}',folder.name):continue
            try:
                job=JobRecord.model_validate(read_json(safe(folder)/'state.json',16384),strict=True).model_dump()
                if job['id']!=folder.name:raise ValueError('Identity mismatch')
                self._jobs[job['id']]=job
                if job['state'] in ('queued','running'):
                    if job['decision']:
                        self._persist(self._change(job,state=job['decision'],phase='finished',error_code='recovered_intent'))
                    elif self._result(job):self._success(job)
                    else:self._persist(self._change(job,state='interrupted',phase='finished',error_code='backend_restarted'))
                elif job['state']=='succeeded' and not self._result(job):
                    self._jobs[job['id']]=self._change(job,state='interrupted',error_code='result_unavailable')
                    self._diagnostics.append(dict(task_id=folder.name,code='result_unavailable'))
            except (JobError,ValidationError,ValueError,OSError):
                self._jobs.pop(folder.name,None)
                self._diagnostics.append(dict(task_id=folder.name,code='invalid_or_future_metadata'))
    def submit(self,filename,language=None):
        if language is not None and language not in _LANGUAGE_CODES:raise JobError('Unsupported transcription language code',422)
        try:source=AudioService(self.uploads).audio_path(filename)
        except AudioError as error:raise JobError(str(error),error.status_code) from error
        with self._lock:
            if self._closing or self._unavailable:raise JobError('Background transcription is unavailable')
            if sum(job['state']=='queued' for job in self._jobs.values())>=5:raise JobError('Transcription queue is full',429)
            # Check platform ownership before accepting an asynchronous job.
            try:owner=self.factory()
            except OwnershipError as error:raise JobError('Safe background process ownership is unavailable') from error
            identity=uuid4().hex;nonce=uuid4().hex;folder=self._folder(identity);folder.mkdir()
            try:
                before=source.stat();count=0;digest=hashlib.sha256()
                snapshot=safe(folder/('input'+source.suffix))
                with source.open('rb') as reader,snapshot.open('xb') as writer:
                    while True:
                        chunk=reader.read(1024*1024)
                        if not chunk:break
                        count+=len(chunk)
                        if count>50*1024*1024:raise JobError('Audio exceeds 50 MiB',413)
                        digest.update(chunk);writer.write(chunk)
                    writer.flush();os.fsync(writer.fileno())
                after=source.stat()
                if not count or (before.st_size,before.st_mtime_ns)!=(after.st_size,after.st_mtime_ns) or count!=before.st_size:
                    raise JobError('Source audio changed or is empty',422)
                from config import WHISPER_MODEL_SIZE,WHISPER_DEVICE,WHISPER_COMPUTE_TYPE
                request=WorkerRequest(task_id=identity,run_nonce=nonce,source_filename=filename,source_sha256=digest.hexdigest(),language=language,
                    model_size=WHISPER_MODEL_SIZE,device=WHISPER_DEVICE,compute_type=WHISPER_COMPUTE_TYPE).model_dump()
                atomic_json(folder/'request.json',request,16384)
                stamp=now()
                job=JobRecord(id=identity,run_nonce=nonce,source_filename=filename,source_sha256=digest.hexdigest(),language=language,
                    state='queued',phase='queued',created_at=stamp,updated_at=stamp).model_dump()
                result=self._persist(job)
            except (OSError,ValidationError) as error:raise JobError('Audio snapshot or job could not be prepared') from error
            finally:owner.close()  # Capability object has no child or handles yet.
            self._wake.set();return result
    def get(self,identity):
        self._folder(identity)
        with self._lock:
            if identity not in self._jobs:raise JobError('Transcription job not found',404)
            return dict(self._jobs[identity])
    def list(self):
        with self._lock:return dict(items=sorted((dict(job) for job in self._jobs.values()),key=lambda item:item['created_at'],reverse=True),diagnostics=list(self._diagnostics))
    def cancel(self,identity):
        with self._lock:
            job=self.get(identity)
            if job['state'] in TERMINAL:return job
            if not job['decision'] and self._result(job):return self._success(job)
            if job['state']=='queued':return self._persist(self._change(job,state='cancelled',phase='finished',decision='cancelled'))
            if not job['decision']:job=self._persist(self._change(job,decision='cancelled',phase='cancelling'))
            self._wake.set();return job
    def _release(self,state,error=None):
        try:
            if self._worker:self._worker.stop()
        except OwnershipError:
            with self._lock:
                self._unavailable=True
                job=self._jobs[self._active_id]
                try:self._persist(self._change(job,phase='cleanup_failed',error_code='cleanup_failed'))
                except JobError:pass
            return False
        with self._lock:
            job=self._jobs[self._active_id]
            try:self._persist(self._change(job,state=job['decision'] or state,phase='finished',error_code=error))
            except JobError:self._unavailable=True
            self._worker=None;self._active_id=None
        return True
    def _tick(self):
        new_job=None
        with self._lock:
            if self._unavailable:return
            if self._active_id is None:
                queued=next((job for job in self._jobs.values() if job['state']=='queued'),None)
                if queued is None or self._closing:return
                new_job=self._persist(self._change(queued,state='running',phase='loading'))
                self._active_id=queued['id'];self._started=time.monotonic()
        if new_job is not None:
            try:
                self._worker=self.factory()
                command=[sys.executable,str(Path(__file__).resolve().parents[1]/'workers/transcription_worker.py'),str(self._folder(new_job['id'])/'request.json')]
                self._worker.start(command,cwd=self._folder(new_job['id']))
            except OwnershipError:self._release('failed','launch_failed')
            return
        with self._lock:
            job=self._jobs[self._active_id]
            if job['decision'] is None and time.monotonic()-self._started>=self.timeout:
                job=self._persist(self._change(job,decision='timed_out',phase='cancelling'))
        if job['decision']:self._release(job['decision']);return
        try:code=self._worker.poll()
        except (OSError,OwnershipError):self._release('failed','worker_unavailable');return
        if code is None:
            progress=self._folder(job['id'])/'progress.json'
            try:
                if safe(progress).exists():
                    stage=read_json(progress,1024)
                    if (not isinstance(stage,dict) or set(stage)!={'schema_version','run_nonce','phase'}
                            or type(stage['schema_version']) is not int or stage['schema_version']!=1
                            or stage['run_nonce']!=job['run_nonce'] or stage['phase'] not in ('loading','transcribing')):
                        raise JobError('Invalid progress protocol')
                    with self._lock:
                        current=self._jobs[job['id']]
                        if not current['decision'] and current['phase']!=stage['phase']:
                            self._persist(self._change(current,phase=stage['phase']))
            except JobError:self._release('failed','invalid_progress')
            return
        if code!=0:self._release('failed','model_unavailable' if code==3 else 'worker_failed');return
        try:
            self._worker.close()  # Reap and kill any owned descendants before publication.
            candidate=Candidate.model_validate(read_json(self._folder(job['id'])/'worker-result.json'),strict=True)
            if (candidate.task_id,candidate.run_nonce,candidate.source_filename,candidate.source_sha256)!=(job['id'],job['run_nonce'],job['source_filename'],job['source_sha256']):raise ValueError('Wrong candidate identity')
            if candidate.transcript.stored_filename!=job['source_filename'] or candidate.transcript.language not in _LANGUAGE_CODES:raise ValueError('Wrong transcript identity')
            record=TranscriptRecord(**candidate.transcript.model_dump(),id=job['id'],task_id=job['id'],run_nonce=job['run_nonce'],source_sha256=job['source_sha256'],created_at=now())
            abort=None
            with self._lock:
                job=self._jobs[job['id']]
                if job['decision']:abort=job['decision']
                elif time.monotonic()-self._started>=self.timeout:
                    self._persist(self._change(job,decision='timed_out',phase='cancelling'));abort='timed_out'
                else:
                    target=safe(self.root/(job['id']+'.json'))
                    if target.exists():raise JobError('Result identity already exists')
                    atomic_json(target,record.model_dump())
                    self._success(job)
                    self._worker=None;self._active_id=None
            if abort:self._release(abort)
        except OwnershipError:self._release('failed','cleanup_failed')
        except (JobError,ValidationError,ValueError,OSError):self._release('failed','invalid_worker_result')
    def _loop(self):
        while not self._stop.is_set():
            try:self._tick()
            except Exception:
                logger.exception('Background transcription scheduler stopped accepting tasks')
                with self._lock:self._unavailable=True
            self._wake.wait(.03);self._wake.clear()
    def close(self):
        storage_failed=False
        with self._lock:
            self._closing=True
            try:
                for job in list(self._jobs.values()):
                    if job['state'] in ('queued','running'):
                        if not job['decision'] and self._result(job):self._success(job)
                        else:
                            active=job['id']==self._active_id
                            decision=job['decision'] or 'cancelled'
                            change=self._change(job,decision=decision,state='running' if active else decision,phase='cancelling' if active else 'finished')
                            try:self._persist(change)
                            except JobError:
                                storage_failed=True
                                if job['state']=='running':self._jobs[job['id']]=change
            finally:self._stop.set();self._wake.set()
        if self._thread:
            self._thread.join(timeout=5)
            if self._thread.is_alive():raise JobError('Transcription scheduler did not stop; ownership retained')
        if self._active_id is not None:
            if not self._release('cancelled'):raise JobError('Transcription worker cleanup failed; ownership retained')
        if storage_failed:raise JobError('Shutdown stopped admission and worker, but state persistence failed')

    def result(self,identity):
        with self._lock:
            job=self.get(identity)
            if job['state']!='succeeded':raise JobError('Transcription result is not ready',409)
            record=self._result(job)
            if record is None:raise JobError('Transcription result is unavailable')
            return record.model_dump()
