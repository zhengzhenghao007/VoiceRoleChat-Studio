"""Offline private candidate producer; never writes public transcripts/state."""
import hashlib,os,sys
from argparse import Namespace
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from schemas.transcription_job import WorkerRequest,Candidate
from services.transcription_job_service import read_json,atomic_json,safe

def fingerprint(path):
    digest=hashlib.sha256();size=0
    with safe(path).open('rb') as handle:
        while True:
            chunk=handle.read(1024*1024)
            if not chunk:break
            size+=len(chunk)
            if size>50*1024*1024:raise ValueError('Snapshot too large')
            digest.update(chunk)
    if not size:raise ValueError('Empty snapshot')
    return digest.hexdigest()

def execute(request_path,model_factory=None):
    os.environ['HF_HUB_OFFLINE']='1';os.environ['TRANSFORMERS_OFFLINE']='1'
    try:
        path=safe(request_path)
        if path.name!='request.json':return 2
        request=WorkerRequest.model_validate(read_json(path,16384),strict=True)
        if path.parent.name!=request.task_id:return 2
        source=safe(path.parent/('input'+Path(request.source_filename).suffix))
        if fingerprint(source)!=request.source_sha256:return 2
        from faster_whisper.tokenizer import _LANGUAGE_CODES
        if request.language is not None and request.language not in _LANGUAGE_CODES:return 2
        # Validate forced local demux before Whisper opens the immutable snapshot.
        import av
        from workers.audio_worker import process
        process(Namespace(input=str(source),extension=source.suffix.lstrip('.'),action='inspect',output=None,start=0,end=None),av)
        atomic_json(path.parent/'progress.json',dict(schema_version=1,run_nonce=request.run_nonce,phase='loading'),1024)
    except Exception:return 2
    try:
        if model_factory is None:
            from faster_whisper import WhisperModel
            model_factory=WhisperModel
        model=model_factory(request.model_size,device=request.device,compute_type=request.compute_type,local_files_only=True)
    except Exception:return 3
    try:
        atomic_json(path.parent/'progress.json',dict(schema_version=1,run_nonce=request.run_nonce,phase='transcribing'),1024)
        from services.transcription_service import infer_path
        transcript=infer_path(source,request.source_filename,request.language,model)
        if fingerprint(source)!=request.source_sha256:return 4
        transcript['transcript_file']='transcripts/'+request.task_id+'.json'
        candidate=Candidate(task_id=request.task_id,run_nonce=request.run_nonce,source_filename=request.source_filename,
            source_sha256=request.source_sha256,transcript=transcript)
        atomic_json(path.parent/'worker-result.json',candidate.model_dump())
        return 0
    except Exception:return 4

if __name__=='__main__':
    raise SystemExit(execute(Path(sys.argv[1])) if len(sys.argv)==2 else 2)
