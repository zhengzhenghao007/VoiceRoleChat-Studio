"""Immutable segmented datasets: owned CPU decode and no-replace directory commit."""
from datetime import datetime,timezone
import hashlib,json,math,os,re,shutil,sys,time,unicodedata,wave
from pathlib import Path
from threading import Lock,RLock
from uuid import uuid4
from pydantic import ValidationError
from services.audio_service import AudioService,AudioError
from services.owned_worker import OwnedWorker,OwnershipError
from services.transcript_review_service import ReviewError
from services.transcription_job_service import safe,read_json,atomic_json,JobError,now
from schemas.segmented_dataset import DatasetWorkerRequest,DatasetWorkerResult,DatasetErrorProtocol,SegmentDatasetManifest

_build_lock=Lock();_retained_lock=RLock();_retained=[]
LANGUAGES={'zh','ja','en','ko','yue'}
class DatasetError(RuntimeError):
    def __init__(self,message,status_code=500):super().__init__(message);self.status_code=status_code

def label(value,name='标注'):
    if not isinstance(value,str) or not value.strip() or any(ch=='|' or unicodedata.category(ch)=='Cc' or ch in '\u2028\u2029' for ch in value):
        raise DatasetError(name+'不能包含竖线、换行或控制字符',422)
    return value.strip()

def digest_file(path,limit):
    count=0;digest=hashlib.sha256()
    with safe(path).open('rb') as reader:
        while True:
            chunk=reader.read(65536)
            if not chunk:break
            count+=len(chunk)
            if count>limit:raise DatasetError('文件超过允许的大小',413)
            digest.update(chunk)
    return digest.hexdigest()

def cleanup_stage(root,stage):
    try:
        root=safe(root);stage=safe(stage)
        if stage.parent!=root or not re.fullmatch(r'\.staging-[0-9a-f]{32}',stage.name):
            raise JobError('Unsafe staging directory')
    except JobError as error:
        raise DatasetError('拒绝清理不属于本轮构建的目录',503) from error
    if stage.exists():shutil.rmtree(stage)

def cleanup_retained():
    with _retained_lock:
        failed=[]
        for owner,root,stage in _retained:
            try:owner.close();cleanup_stage(root,stage)
            except (OwnershipError,OSError,DatasetError):failed.append((owner,root,stage))
        _retained[:]=failed
        if failed:raise DatasetError('切片进程或暂存目录未能清理，已阻止新构建',503)

class SegmentedDatasets:
    def __init__(self,root,uploads,reviews,characters,*,worker_factory=OwnedWorker,timeout=None):
        from config import DATASET_BUILD_TIMEOUT
        self.root=Path(root).resolve();self.uploads=Path(uploads).resolve();self.characters=Path(characters).resolve()
        self.reviews=reviews;self.factory=worker_factory;self.timeout=DATASET_BUILD_TIMEOUT if timeout is None else timeout
    def _folder(self,name):
        from schemas.segmented_dataset import SegmentDatasetRequest
        try:
            if not isinstance(name,str) or not re.fullmatch(r'[A-Za-z0-9_-]{1,100}',name):raise ValueError('name')
            SegmentDatasetRequest.normal_directory(name)
            return safe(self.root/name)
        except (ValueError,JobError) as error:raise DatasetError('数据集不存在或名称无效',404) from error
    def _review(self,doc,request):
        if doc['kind']!='review':raise DatasetError('请先保存独立校对副本再制作分段数据集',422)
        if doc['revision']!=request.expected_revision or doc['sha256']!=request.expected_sha256:
            raise DatasetError('校对记录已改变，请重新加载后再构建',409)
        if doc['transcript']['language'] not in LANGUAGES:raise DatasetError('数据集仅支持 zh/ja/en/ko/yue',422)
        if len(doc['transcript']['segments'])>1000:raise DatasetError('单次数据集最多1000个片段',422)
        for index,row in enumerate(doc['transcript']['segments'],1):label(row['text'],'第'+str(index)+'段文字')
    def _speaker(self,identity):
        if not re.fullmatch(r'[A-Za-z0-9_-]{1,100}',identity):raise DatasetError('角色ID无效',422)
        try:
            data=read_json(safe(self.characters/identity/'config.json'),1024*1024)
            if not isinstance(data,dict) or type(data.get('schema_version',1)) is not int or data.get('schema_version',1) not in (1,2):
                raise DatasetError('未知版本的角色配置',422)
            if data.get('id',identity)!=identity:raise DatasetError('角色身份不一致',422)
            name=label(data.get('name'),'说话人名称')
            if len(name)>100:raise DatasetError('说话人名称最多100字符',422)
            return name
        except (JobError,OSError) as error:raise DatasetError('角色配置不存在或无法读取',404) from error
    def _origin_audio(self,doc,current_hash):
        try:
            path=safe(self.reviews.root/'.review_sources'/(doc['source_sha256']+'.json'))
            if digest_file(path,8*1024*1024)!=doc['source_sha256']:raise ValueError('source snapshot')
            source=read_json(path)
            if not isinstance(source,dict):raise ValueError('source metadata')
        except (OSError,JobError,ValueError,DatasetError) as error:
            raise DatasetError('校对来源快照缺失或损坏，请检查原始转写',422) from error
        if source.get('schema_version')==2 and source.get('source_sha256')!=current_hash:
            raise DatasetError('原音内容与原始转写任务不一致，请重新转写或恢复原音',409)
    def _worker_error(self,stage,request,code):
        if code==3:raise DatasetError('当前 Python 的 PyAV 解码器不可用',503)
        try:
            problem=DatasetErrorProtocol.model_validate(read_json(safe(stage/'worker-error.json'),1024),strict=True)
            if problem.task_id!=request.task_id or problem.run_nonce!=request.run_nonce:raise ValueError('identity')
        except (JobError,ValidationError,ValueError):raise DatasetError('切片进程返回无效的错误协议',503)
        messages={'silence':'片段为全静音','source_window':'片段超过真实解码音频边界','resource_limit':'音频超出处理资源预算','changed_source':'音频快照发生改变','invalid_media':'音频格式、完整性或片段边界校验失败','io_error':'切片文件无法写入'}
        prefix='第'+str(problem.segment)+'段：' if problem.segment else ''
        raise DatasetError(prefix+messages[problem.code],500 if problem.code=='io_error' else 422)
    def _candidate(self,stage,request):
        try:
            result=DatasetWorkerResult.model_validate(read_json(safe(stage/'worker-result.json'),1024*1024),strict=True)
            if (result.task_id,result.run_nonce,result.source_sha256)!=(request.task_id,request.run_nonce,request.source_sha256):raise ValueError('identity')
            if len(result.clips)!=len(request.windows):raise ValueError('count')
            for index,(clip,window) in enumerate(zip(result.clips,request.windows),1):
                first,last=round(window.start*32000),round(window.end*32000)
                if (clip.index,clip.filename,clip.start_frame,clip.end_frame,clip.frames)!=(index,f'audio/segment_{index:04d}.wav',first,last,last-first):raise ValueError('window')
                if abs(clip.duration_seconds-clip.frames/32000)>1e-9 or last>round(result.source_duration_seconds*32000):raise ValueError('duration')
                path=safe(stage/clip.filename)
                if path.stat().st_size!=44+clip.frames*2 or digest_file(path,1920044)!=clip.sha256:raise ValueError('hash or size')
                with wave.open(str(path),'rb') as handle:
                    if (handle.getnchannels(),handle.getsampwidth(),handle.getframerate(),handle.getnframes(),handle.getcomptype())!=(1,2,32000,clip.frames,'NONE'):raise ValueError('format')
                    count=0
                    while True:
                        chunk=handle.readframes(4096)
                        if not chunk:break
                        count+=len(chunk)
                    if count!=clip.frames*2:raise ValueError('truncated PCM')
            return result
        except (JobError,ValidationError,ValueError,OSError,EOFError,wave.Error,DatasetError) as error:
            raise DatasetError('切片进程结果、WAV或哈希校验失败',503) from error
    def build(self,request):
        if not _build_lock.acquire(blocking=False):raise DatasetError('另一数据集正在构建，请稍后重试',429)
        stage=None;owner=None;published=False;retained=False
        try:
            cleanup_retained()
            final=self._folder(request.dataset_name)
            if final.exists():raise DatasetError('同名数据集已存在，禁止覆盖',409)
            speaker=self._speaker(request.character_id)
            with self.reviews.locked_snapshot(request.review_id) as (doc,raw):
                self._review(doc,request)
                body=doc['transcript']
                try:
                    source=AudioService(self.uploads).audio_path(body['stored_filename'])
                except AudioError as error:raise DatasetError('校对记录引用的原音不存在或路径无效',422) from error
                identity=uuid4().hex;nonce=uuid4().hex
                try:windows=DatasetWorkerRequest(task_id=identity,run_nonce=nonce,source_filename=source.name,source_sha256='0'*64,
                    windows=[dict(start=row['start'],end=row['end']) for row in body['segments']]).windows
                except ValidationError as error:raise DatasetError('每段应为0.3–30秒，且按时间顺序、不重叠',422) from error
                for index in range(1,len(windows)+1):label(str(final/'audio'/f'segment_{index:04d}.wav'),'音频标注路径')
                safe(self.root).mkdir(parents=True,exist_ok=True)
                stage=safe(self.root/('.staging-'+identity));stage.mkdir()
                with safe(stage/'review.json').open('xb') as output:output.write(raw);output.flush();os.fsync(output.fileno())
            snapshot=safe(stage/('input'+source.suffix));before=source.stat();count=0;digest=hashlib.sha256()
            with source.open('rb') as reader,snapshot.open('xb') as output:
                while True:
                    chunk=reader.read(1024*1024)
                    if not chunk:break
                    count+=len(chunk)
                    if count>50*1024*1024:raise DatasetError('原音超过50MiB',413)
                    digest.update(chunk);output.write(chunk)
                output.flush();os.fsync(output.fileno())
            after=source.stat()
            if not count or count!=before.st_size or (before.st_size,before.st_mtime_ns)!=(after.st_size,after.st_mtime_ns):raise DatasetError('复制期间原音发生改变或为空',409)
            worker_request=DatasetWorkerRequest(task_id=identity,run_nonce=nonce,source_filename=source.name,source_sha256=digest.hexdigest(),windows=windows)
            self._origin_audio(doc,worker_request.source_sha256)
            atomic_json(stage/'request.json',worker_request.model_dump(),256*1024)
            try:owner=self.factory();started=time.monotonic();owner.start([sys.executable,str(Path(__file__).resolve().parents[1]/'workers/dataset_worker.py'),str(stage/'request.json')],cwd=stage)
            except OwnershipError as error:raise DatasetError('无法建立安全的切片进程所有权',503) from error
            while owner.poll() is None:
                if time.monotonic()-started>=self.timeout:raise DatasetError('切片构建超时',504)
                time.sleep(.01)
            code=owner.poll();owner.close()
            if code!=0:self._worker_error(stage,worker_request,code)
            candidate=self._candidate(stage,worker_request)
            if abs(candidate.source_duration_seconds-body['duration'])>.02:
                raise DatasetError('原音解码时长与校对记录不一致，请重新转写或检查原音',422)
            if digest_file(snapshot,50*1024*1024)!=worker_request.source_sha256 or digest_file(stage/'review.json',8*1024*1024)!=request.expected_sha256:raise DatasetError('构建输入快照校验失败',503)
            lines=[];clips=[];warnings=[]
            for clip,row in zip(candidate.clips,body['segments']):
                path=label(str(final/clip.filename),'音频标注路径');text=label(row['text'],'片段文字')
                lines.append('|'.join([path,speaker,body['language'],text]))
                clips.append(dict(clip.model_dump(),start_seconds=row['start'],end_seconds=row['end'],text=text))
                warnings.extend(f'segment_{clip.index:04d}:{warning}' for warning in clip.warnings)
            manifest=SegmentDatasetManifest(dataset_name=request.dataset_name,character_id=request.character_id,speaker_name=speaker,language=body['language'],
                review_id=request.review_id,review_revision=request.expected_revision,review_sha256=request.expected_sha256,source_audio='uploads/'+source.name,source_audio_sha256=worker_request.source_sha256,
                source_transcript_snapshot='datasets/'+request.dataset_name+'/review.json',annotation_file='datasets/'+request.dataset_name+'/transcript.list',entry_count=len(clips),
                total_duration=sum(clip.frames for clip in candidate.clips)/32000,created_at=now(),warnings=warnings,clips=clips)
            with safe(stage/'transcript.list').open('x',encoding='utf8',newline='\n') as output:output.write('\n'.join(lines)+'\n');output.flush();os.fsync(output.fileno())
            atomic_json(stage/'dataset.json',manifest.model_dump(),1024*1024)
            for filename in (snapshot.name,'request.json','worker-result.json','worker-error.json'):
                safe(stage/filename).unlink(missing_ok=True)
            with self.reviews.locked_snapshot(request.review_id) as (current,_):
                self._review(current,request)
                current_source=source.stat()
                if (current_source.st_size,current_source.st_mtime_ns)!=(after.st_size,after.st_mtime_ns):raise DatasetError('构建期间原音发生改变',409)
                if self._folder(request.dataset_name).exists():raise DatasetError('同名数据集已存在，禁止覆盖',409)
                try:os.rename(safe(stage),final)
                except OSError as error:
                    if final.exists():raise DatasetError('同名数据集已存在，禁止覆盖',409) from error
                    raise DatasetError('数据集发布失败，原有数据集保持不变') from error
                published=True
            return manifest.model_dump()
        except OwnershipError as error:raise DatasetError('切片进程不可用，未发布数据集',503) from error
        except ReviewError as error:raise DatasetError(str(error),error.status_code) from error
        except (JobError,ValidationError,OSError) as error:raise DatasetError('数据集快照或文件存储失败') from error
        finally:
            try:
                if owner is not None:
                    try:owner.close()
                    except OwnershipError:
                        with _retained_lock:_retained.append((owner,self.root,stage))
                        retained=True
                if stage is not None and not published and not retained:cleanup_stage(self.root,stage)
                if retained:raise DatasetError('切片进程清理未完成，已保留所有权和暂存文件',503)
            finally:_build_lock.release()
    def get(self,name):
        folder=self._folder(name)
        try:
            data=read_json(safe(folder/'dataset.json'),1024*1024)
            if not isinstance(data,dict):raise ValueError('metadata')
            version=data.get('schema_version',0)
            if type(version) is not int:raise ValueError('version')
            if version==2:
                manifest=SegmentDatasetManifest.model_validate(data,strict=True)
                if manifest.dataset_name!=name or manifest.entry_count!=len(manifest.clips):raise ValueError('identity')
                if manifest.annotation_file!='datasets/'+name+'/transcript.list' or manifest.source_transcript_snapshot!='datasets/'+name+'/review.json':raise ValueError('paths')
                if abs(sum(clip.frames for clip in manifest.clips)/32000-manifest.total_duration)>1e-9:raise ValueError('duration')
                for index,clip in enumerate(manifest.clips,1):
                    if clip.index!=index or clip.filename!=f'audio/segment_{index:04d}.wav':raise ValueError('clips')
                    safe(folder/clip.filename)
                return manifest.model_dump()
            if version!=0:raise DatasetError('未知版本数据集，原文件已保留',409)
            if data.get('dataset_name',data.get('experiment_name'))!=name:raise ValueError('identity')
            return dict(data,dataset_name=name,validation_status='legacy_unverified')
        except DatasetError:raise
        except (JobError,ValueError,ValidationError,OSError) as error:raise DatasetError('数据集不存在或元数据损坏',404) from error
    def list(self):
        items=[];diagnostics=[]
        if not self.root.exists():return dict(items=items,diagnostics=diagnostics)
        for folder in self.root.iterdir():
            if not re.fullmatch(r'[A-Za-z0-9_-]{1,100}',folder.name):continue
            try:
                data=self.get(folder.name)
                items.append(dict(dataset_name=folder.name,schema_version=data.get('schema_version',0),character_id=data.get('character_id'),language=data.get('language'),entry_count=data.get('entry_count'),total_duration=data.get('total_duration'),warnings=data.get('warnings',['legacy_unverified'])))
            except DatasetError:diagnostics.append(dict(dataset_name=folder.name,code='invalid_or_future_metadata'))
        return dict(items=sorted(items,key=lambda item:item['dataset_name']),diagnostics=diagnostics)
