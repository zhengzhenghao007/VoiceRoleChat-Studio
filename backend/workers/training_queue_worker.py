"""Trusted whole-pipeline worker; canonical states and model commit belong to parent."""
import hashlib,json,sys,math,time
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from schemas.training_queue import WorkerRequest,Progress,Candidate
from services.training_queue_store import input_fingerprints,digest,QueueError
from services.transcription_job_service import safe,read_json,atomic_json,JobError
from services.training_command import TrainingCommands
from workers import training_worker

def publish_progress(path,data):
    # A normal Windows reader may temporarily deny destination replacement.
    deadline=time.monotonic()+.5
    while True:
        try:return atomic_json(path,data,8192)
        except JobError as error:
            if not isinstance(error.__cause__,PermissionError) or time.monotonic()>=deadline:raise
            time.sleep(.01)

class PipelineRuntime:
    def __init__(self,request,folder,request_sha):
        self.request=request;self.folder=folder;self.request_sha=request_sha;self.sequence=0;self.completed=False
        self.experiment_root=safe(folder/'experiments')
        self.job=dict(request.request.model_dump(),job_id=request.job_id,status='queued')
    def load(self,identity):
        if identity!=self.request.job_id:raise ValueError('Task identity mismatch')
        return dict(self.job)
    def prepare_legacy(self,job,experiment_name,work):
        from services.training_dataset import exclusive_directory
        from services.training_snapshot import copy_file
        from services.dataset_service import build_gpt_sovits_dataset
        from schemas.dataset import DatasetBuildRequest
        root=exclusive_directory(work,'legacy-inputs')
        characters=exclusive_directory(root,'characters');character=exclusive_directory(characters,job['character_id'])
        uploads=exclusive_directory(root,'uploads');transcripts=exclusive_directory(root,'transcripts')
        datasets=exclusive_directory(work,'legacy-datasets');config=self.request.runtime;budget=[128*1024*1024]
        copies=[('character',Path(config.CHARACTERS_DIR)/job['character_id']/'config.json',character/'config.json',1024*1024),
            ('audio',Path(config.UPLOAD_DIR)/job['stored_filename'],uploads/job['stored_filename'],50*1024*1024),
            ('transcript',Path(config.TRANSCRIPTS_DIR)/job['transcript_filename'],transcripts/job['transcript_filename'],8*1024*1024)]
        for key,source,target,limit in copies:
            if copy_file(source,target,limit,budget)!=self.request.fingerprints[key]:raise ValueError('Legacy input changed during snapshot')
        metadata=build_gpt_sovits_dataset(DatasetBuildRequest(character_id=job['character_id'],stored_filename=job['stored_filename'],transcript_filename=job['transcript_filename'],dataset_name=experiment_name),roots=(characters,datasets,transcripts,uploads),cleanup_on_failure=False)
        directory=safe(datasets/experiment_name);annotation=safe(directory/'transcript.list')
        provenance=dict(schema_version=1,job_id=job['job_id'],mode='legacy',source_hashes=self.request.fingerprints,snapshot_relative_path=str(directory.relative_to(work)),annotation_sha256=digest(annotation,8*1024*1024))
        atomic_json(work/'input-provenance.json',provenance,8192)
        metadata.update(source_audio='uploads/'+job['stored_filename'],annotation_file=str(annotation),training_input_provenance=provenance)
        return directory,safe(directory/'audio'),annotation,metadata
    def update(self,identity,**values):
        if identity!=self.request.job_id:raise ValueError('Task identity mismatch')
        self.sequence+=1
        status=values.get('job_status',self.job['status']);self.job['status']=status
        base=dict(job_id=identity,run_nonce=self.request.run_nonce,request_sha256=self.request_sha)
        if status=='completed':
            stage=safe(self.folder/'export'/identity)
            candidate=Candidate(**base,manifest_sha256=digest(stage/'manifest.json',1024*1024),gpt_sha256=digest(stage/'gpt_v2pro.ckpt',8*1024**3),sovits_sha256=digest(stage/'sovits_v2pro.pth',8*1024**3))
            atomic_json(self.folder/'candidate.json',candidate.model_dump(),8192);self.completed=True
        progress=Progress(**base,sequence=self.sequence,status='failed' if status=='failed' else ('training' if status in ('training','completed') else 'preparing'),progress=min(99,values.get('progress',0)),current_step=values.get('current_step','Training pipeline'),error_code='pipeline_failed' if status=='failed' else None)
        publish_progress(self.folder/'progress.json',progress.model_dump())
        return dict(self.job)

def execute(path):
    request_path=safe(path);folder=safe(request_path.parent)
    with request_path.open('rb') as reader:raw=reader.read(65537)
    if len(raw)>65536:raise ValueError('Request too large')
    request=WorkerRequest.model_validate(json.loads(raw),strict=True)
    jobs=safe(request.runtime.TRAINING_JOBS_DIR)
    if request_path!=safe(jobs/'.queue'/request.job_id/'request.json'):raise ValueError('Unsafe request location')
    for key,value in request.runtime.model_dump().items():
        if key not in ('GPT_SOVITS_GPU','TRAINING_COMMAND_TIMEOUT'):safe(value)
    runtime=PipelineRuntime(request,folder,hashlib.sha256(raw).hexdigest())
    if input_fingerprints(request.request,request.runtime)!=request.fingerprints:
        runtime.sequence=1
        progress=Progress(job_id=request.job_id,run_nonce=request.run_nonce,request_sha256=runtime.request_sha,sequence=1,status='failed',progress=0,current_step='Source changed while queued',error_code='input_changed')
        publish_progress(folder/'progress.json',progress.model_dump());return 2
    timeout=float(request.runtime.TRAINING_COMMAND_TIMEOUT)
    if not math.isfinite(timeout) or not 0<timeout<=86400:raise ValueError('Invalid command timeout')
    values={key:value if key=='GPT_SOVITS_GPU' else safe(value) for key,value in request.runtime.model_dump().items() if key!='TRAINING_COMMAND_TIMEOUT'}
    from services import training_command
    previous={key:getattr(training_worker,key) for key in values}
    previous['MODELS_DIR']=training_worker.MODELS_DIR;previous_runner=training_command._runner
    try:
        for key,value in values.items():setattr(training_worker,key,value)
        training_worker.MODELS_DIR=safe(folder/'export');training_worker.MODELS_DIR.mkdir(exist_ok=False)
        training_command._runner=TrainingCommands(request.runtime.GPT_SOVITS_ROOT,jobs,python=request.runtime.GPT_SOVITS_PYTHON,timeout=timeout)
        try:training_worker.run_training_job(request.job_id,runtime=runtime)
        finally:training_command.close_training_commands()
    finally:
        for key,value in previous.items():setattr(training_worker,key,value)
        training_command._runner=previous_runner

    return 0 if runtime.completed else 2

if __name__=='__main__':
    try:raise SystemExit(execute(Path(sys.argv[1])))
    except Exception:raise SystemExit(2)
