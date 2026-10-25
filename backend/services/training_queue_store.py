"""Bounded training records and parent-only atomic model publication."""
import hashlib,json,os,re
from pathlib import Path
from uuid import uuid4
from pydantic import ValidationError
from schemas.training import TrainingJobResponse
from schemas.training_queue import JobRecord,WorkerRequest,RuntimeConfig,Candidate
from services.transcription_job_service import safe,read_json,atomic_json,now,JobError
from services.training_dataset import component,validate_prepared_dataset

class QueueError(RuntimeError):
    def __init__(self,message,code=503):super().__init__(message);self.status_code=code

def digest(path,limit):
    count=0;result=hashlib.sha256()
    try:
        path=safe(path)
        if path.stat().st_size>limit:raise ValueError('File exceeds limit')
        with path.open('rb') as reader:
            while True:
                block=reader.read(1024*1024)
                if not block:break
                count+=len(block)
                if count>limit:raise ValueError('File exceeds limit')
                result.update(block)
    except (OSError,JobError,ValueError) as error:raise QueueError('Training file missing, unsafe or too large',422) from error
    return result.hexdigest()

def input_fingerprints(request,runtime):
    try:
        values=runtime.model_dump() if isinstance(runtime,RuntimeConfig) else runtime
        character=safe(component(values['CHARACTERS_DIR'],request.character_id)/'config.json')
        config=read_json(character,1024*1024)
        if not isinstance(config,dict) or config.get('id',request.character_id)!=request.character_id:raise ValueError('Character identity')
        result={'character':digest(character,1024*1024)}
        if request.dataset_name:
            folder=validate_prepared_dataset(values['DATASETS_DIR'],request.dataset_name,request.character_id)[0]
            result['dataset']=digest(folder/'dataset.json',1024*1024)
        else:
            result['audio']=digest(safe(Path(values['UPLOAD_DIR'])/request.stored_filename),50*1024*1024)
            result['transcript']=digest(safe(Path(values['TRANSCRIPTS_DIR'])/request.transcript_filename),8*1024*1024)
        return result
    except QueueError:raise
    except (OSError,ValueError,JobError,RuntimeError) as error:raise QueueError('Training source failed validation',422) from error

class TrainingStore:
    def __init__(self,jobs,models,runtime):
        self.jobs=safe(jobs);self.models=safe(models);self.directory=safe(self.jobs/'.queue')
        self.directory.mkdir(parents=True,exist_ok=True)
        self.runtime=RuntimeConfig.model_validate(runtime,strict=True);self._sequence=0
        if safe(self.runtime.TRAINING_JOBS_DIR)!=self.jobs:raise QueueError('Training root mismatch')
    def folder(self,identity):
        if not isinstance(identity,str) or not re.fullmatch(r'[0-9a-f]{32}',identity):raise QueueError('Training job not found',404)
        return safe(self.directory/identity)
    def create(self,request):
        hashes=input_fingerprints(request,self.runtime)
        self._sequence+=1
        identity=uuid4().hex;nonce=uuid4().hex
        protocol=WorkerRequest(job_id=identity,run_nonce=nonce,request=request,runtime=self.runtime,fingerprints=hashes)
        encoded=json.dumps(protocol.model_dump(),ensure_ascii=False,allow_nan=False).encode('utf8')
        if len(encoded)>65536:raise QueueError('Training request exceeds size limit',422)
        folder=self.folder(identity);folder.mkdir(exist_ok=False)
        with (folder/'request.json').open('xb') as writer:writer.write(encoded);writer.flush();os.fsync(writer.fileno())
        stamp=now();data=JobRecord(**request.model_dump(),job_id=identity,run_nonce=nonce,request_sha256=hashlib.sha256(encoded).hexdigest(),created_at=stamp,updated_at=stamp,enqueue_order=self._sequence).model_dump()
        return self.persist(data)
    def persist(self,job):
        try:
            checked=JobRecord.model_validate(job,strict=True).model_dump()
            atomic_json(self.folder(checked['job_id'])/'state.json',checked,65536)
            return checked
        except (OSError,JobError,ValidationError) as error:raise QueueError('Training state could not be saved') from error
    def load(self,identity):
        try:
            data=read_json(self.folder(identity)/'state.json',65536)
            if type(data.get('schema_version')) is not int or data['schema_version']!=1:raise ValueError('Version')
            record=JobRecord.model_validate(data,strict=True)
            if record.job_id!=identity:raise ValueError('Identity')
            return record.model_dump()
        except (JobError,ValueError,ValidationError,OSError,AttributeError) as error:raise QueueError('Training state missing or invalid',404) from error
    def request(self,job):
        try:
            path=self.folder(job['job_id'])/'request.json'
            if digest(path,65536)!=job['request_sha256']:raise ValueError('Request changed')
            data=WorkerRequest.model_validate(read_json(path,65536),strict=True)
            if data.job_id!=job['job_id'] or data.run_nonce!=job['run_nonce']:raise ValueError('Identity')
            if data.request.model_dump()!={key:job[key] for key in type(data.request).model_fields}:raise ValueError('Request identity')
            if safe(data.runtime.TRAINING_JOBS_DIR)!=self.jobs:raise ValueError('Root')
            return data
        except (QueueError,JobError,ValueError,ValidationError,OSError) as error:raise QueueError('Training request missing or invalid') from error
    def verify_inputs(self,request):
        if input_fingerprints(request.request,request.runtime)!=request.fingerprints:raise QueueError('Training source changed while queued',422)
    def legacy(self,identity):
        self.folder(identity)
        try:
            data=read_json(safe(self.jobs/(identity+'.json')),65536)
            if not isinstance(data,dict) or data.get('schema_version',0)!=0 or data.get('job_id')!=identity:raise ValueError('Legacy identity/version')
            return TrainingJobResponse.model_validate(data).model_dump()
        except (JobError,ValidationError,ValueError,OSError) as error:raise QueueError('Legacy training record unavailable',404) from error
    def _manifest(self,folder,job):
        if {path.name for path in folder.iterdir()}!={'manifest.json','gpt_v2pro.ckpt','sovits_v2pro.pth'}:raise ValueError('Unexpected export files')
        data=read_json(safe(folder/'manifest.json'),1024*1024)
        if not isinstance(data,dict) or data.get('job_id')!=job['job_id'] or data.get('character_id')!=job['character_id'] or data.get('version')!='v2Pro':raise ValueError('Model identity')
        for key in ('source_gpt_model','source_sovits_model'):
            if not isinstance(data.get(key),str) or not data[key] or len(data[key])>32767:raise ValueError('Invalid source model path')
        for key,name in [('gpt_model','gpt_v2pro.ckpt'),('sovits_model','sovits_v2pro.pth')]:
            if data.get(key)!=str(folder/name):raise ValueError('Model path')
        return data
    def validate_export(self,job):
        try:
            folder=self.folder(job['job_id']);stage=safe(folder/'export'/job['job_id'])
            candidate=Candidate.model_validate(read_json(folder/'candidate.json',8192),strict=True)
            for key in ('job_id','run_nonce','request_sha256'):
                if getattr(candidate,key)!=job[key]:raise ValueError('Candidate identity')
            if digest(stage/'manifest.json',1024*1024)!=candidate.manifest_sha256:raise ValueError('Manifest hash')
            manifest=self._manifest(stage,job)
            for side,name in [('gpt','gpt_v2pro.ckpt'),('sovits','sovits_v2pro.pth')]:
                file=safe(stage/name)
                if not 0<file.stat().st_size<=8*1024**3 or digest(file,8*1024**3)!=getattr(candidate,side+'_sha256'):raise ValueError('Weight hash')
                source=safe(manifest['source_'+side+'_model']);root=safe(self.jobs/job['job_id']/'weights'/side)
                if source.parent!=root or digest(source,8*1024**3)!=getattr(candidate,side+'_sha256'):raise ValueError('Source weight')
            return stage,manifest,candidate.model_dump()
        except (QueueError,ValueError,JobError,ValidationError,OSError,KeyError) as error:raise QueueError('Training candidate failed integrity validation') from error
    def publish(self,job,prepared):
        try:
            stage,manifest,proof=prepared;final=component(self.models,job['job_id'])
            if final.exists():raise FileExistsError('Model output exists')
            manifest=dict(manifest,gpt_model=str(final/'gpt_v2pro.ckpt'),sovits_model=str(final/'sovits_v2pro.pth'),training_task=proof)
            atomic_json(stage/'manifest.json',manifest,1024*1024)
            os.rename(safe(stage),final)
            return final
        except (OSError,JobError,ValueError) as error:raise QueueError('Training model publication failed; existing output preserved') from error
    def committed(self,job):
        try:
            folder=component(self.models,job['job_id']);manifest=self._manifest(folder,job)
            proof=Candidate.model_validate(manifest.get('training_task'),strict=True)
            if any(getattr(proof,key)!=job[key] for key in ('job_id','run_nonce','request_sha256')):return False
            for side,name in [('gpt','gpt_v2pro.ckpt'),('sovits','sovits_v2pro.pth')]:
                if digest(folder/name,8*1024**3)!=getattr(proof,side+'_sha256'):return False
            return True
        except (QueueError,JobError,ValueError,OSError,ValidationError):return False
