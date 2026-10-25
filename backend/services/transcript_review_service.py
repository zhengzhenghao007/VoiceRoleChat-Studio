"""Read-only transcript discovery and atomic, hash-protected review copies."""
from datetime import datetime,timezone
import hashlib,json,os,re,tempfile
from pathlib import Path
from threading import RLock
from uuid import uuid4
from pydantic import ValidationError
from faster_whisper.tokenizer import _LANGUAGE_CODES
from schemas.transcription import TranscriptionResponse
from schemas.transcription_job import TranscriptRecord
from schemas.transcript_review import ReviewRecord,RecordDocument
from services.audio_service import AudioService,AudioError
from services.transcription_job_service import safe,atomic_json,JobError,MAX_RESULT,now

_record_lock=RLock()
class ReviewError(RuntimeError):
    def __init__(self,message,status_code=500):super().__init__(message);self.status_code=status_code

class TranscriptReviews:
    def __init__(self,root,uploads):self.root=Path(root).resolve();self.uploads=Path(uploads).resolve()
    def _path(self,identity):
        if not isinstance(identity,str) or not re.fullmatch(r'[0-9a-f]{32}',identity):raise ReviewError('Transcript not found',404)
        try:return safe(self.root/(identity+'.json'))
        except JobError as error:raise ReviewError('Unsafe transcript path',404) from error
    def _bytes(self,path):
        try:
            with safe(path).open('rb') as source:raw=source.read(MAX_RESULT+1)
            if len(raw)>MAX_RESULT:raise ReviewError('Transcript exceeds size budget')
            return raw
        except FileNotFoundError as error:raise ReviewError('Transcript not found',404) from error
        except (OSError,JobError) as error:raise ReviewError('Transcript could not be read') from error
    def _document(self,identity,raw):
        try:
            data=json.loads(raw)
            if not isinstance(data,dict):raise ValueError('Invalid transcript')
            version=data.get('schema_version',0)
            if type(version) is not int or version not in (0,2,3):raise ReviewError('Unsupported transcript version',409)
            if version==3:
                record=ReviewRecord.model_validate(data,strict=True)
                if record.id!=identity:raise ValueError('Wrong identity')
                kind='review';revision=record.revision
            elif version==2:
                record=TranscriptRecord.model_validate(data,strict=True)
                if record.id!=identity:raise ValueError('Wrong identity')
                kind='job';revision=1
            else:
                data=dict(data,transcript_file='transcripts/'+identity+'.json')
                record=TranscriptionResponse.model_validate(data,strict=True);kind='legacy';revision=0
            if record.language not in _LANGUAGE_CODES:raise ValueError('Invalid language')
            payload=TranscriptionResponse.model_validate(record.model_dump()).model_dump()
            try:
                AudioService(self.uploads).audio_path(record.stored_filename)
                audio='/api/voices/'+record.stored_filename+'/audio'
            except AudioError:audio=None
            stamp=datetime.fromtimestamp(self._path(identity).stat().st_mtime,timezone.utc).isoformat()
            return RecordDocument(id=identity,kind=kind,revision=revision,sha256=hashlib.sha256(raw).hexdigest(),editable=kind=='review',
                transcript=payload,audio_url=audio,created_at=getattr(record,'created_at',stamp),updated_at=getattr(record,'updated_at',getattr(record,'created_at',stamp)),
                source_id=getattr(record,'source_id',None),source_sha256=getattr(record,'source_sha256',None)).model_dump()
        except (ValueError,ValidationError,OSError,RecursionError) as error:raise ReviewError('Malformed transcript data') from error
    def get(self,identity):
        with _record_lock:return self._document(identity,self._bytes(self._path(identity)))
    def list(self):
        items=[];diagnostics=[]
        if not self.root.exists():return dict(items=items,diagnostics=diagnostics)
        with _record_lock:
            for path in self.root.glob('*.json'):
                if not re.fullmatch(r'[0-9a-f]{32}\.json',path.name):continue
                try:
                    doc=self.get(path.stem);body=doc['transcript']
                    items.append(dict(id=doc['id'],kind=doc['kind'],revision=doc['revision'],language=body['language'],duration=body['duration'],stored_filename=body['stored_filename'],
                        text_preview=body['text'][:160],segment_count=len(body['segments']),updated_at=doc['updated_at']))
                except ReviewError as error:diagnostics.append(dict(record_id=path.stem,code='unsupported_version' if error.status_code==409 else 'invalid_record'))
        return dict(items=sorted(items,key=lambda value:value['updated_at'],reverse=True),diagnostics=diagnostics)
    def _snapshot(self,raw,digest):
        temporary=None
        try:
            directory=safe(self.root/'.review_sources');directory.mkdir(exist_ok=True)
            target=safe(directory/(digest+'.json'))
            if target.exists():
                if self._bytes(target)!=raw:raise ReviewError('Existing source snapshot is inconsistent')
                return
            with tempfile.NamedTemporaryFile(dir=directory,suffix='.tmp',delete=False) as output:
                temporary=Path(output.name);output.write(raw);output.flush();os.fsync(output.fileno())
            os.replace(temporary,safe(target))
        except (OSError,JobError) as error:raise ReviewError('Source snapshot could not be preserved') from error
        finally:
            if temporary is not None:
                try:temporary.unlink(missing_ok=True)
                except OSError:pass
    def _record(self,data,content):
        if content.language not in _LANGUAGE_CODES:raise ReviewError('Unsupported review language',422)
        if any(row.end>data['duration']+.01 for row in content.segments):raise ReviewError('Segment exceeds source duration',422)
        values=dict(data,language=content.language,segments=[row.model_dump() for row in content.segments],text=' '.join(row.text for row in content.segments))
        try:return ReviewRecord.model_validate(values).model_dump()
        except ValidationError as error:raise ReviewError('Invalid review content or source reference',422) from error
    def create(self,request):
        with _record_lock:
            path=self._path(request.source_id);raw=self._bytes(path);source=self._document(request.source_id,raw)
            if source['kind']=='review':raise ReviewError('Edit the existing review rather than creating a chained review',409)
            if source['sha256']!=request.expected_source_sha256:raise ReviewError('Source changed; reload before saving a corrected copy',409)
            identity=uuid4().hex;stamp=now()
            data=dict(source['transcript'],schema_version=3,kind='review',id=identity,revision=1,source_id=request.source_id,source_sha256=source['sha256'],source_revision=source['revision'],
                created_at=stamp,updated_at=stamp,transcript_file='transcripts/'+identity+'.json')
            result=self._record(data,request)
            self._snapshot(raw,source['sha256'])
            try:
                target=self._path(identity)
                if target.exists():raise ReviewError('Review identity already exists',409)
                atomic_json(target,result)
            except JobError as error:raise ReviewError('Review could not be saved; source was preserved') from error
            return self.get(identity)
    def update(self,identity,request):
        with _record_lock:
            doc=self.get(identity)
            if not doc['editable']:raise ReviewError('Original transcript is read-only; save a corrected copy',409)
            if doc['revision']!=request.expected_revision or doc['sha256']!=request.expected_sha256:
                raise ReviewError('Review changed; reload explicitly or retain your draft',409)
            raw=self._bytes(self._path(identity));data=json.loads(raw)
            result=self._record(dict(data,revision=doc['revision']+1,updated_at=now()),request)
            try:atomic_json(self._path(identity),result)
            except JobError as error:raise ReviewError('Review could not be saved; previous revision was preserved') from error
            return self.get(identity)
