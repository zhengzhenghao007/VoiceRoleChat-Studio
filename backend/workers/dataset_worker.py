"""One-pass local audio decode/resample and deterministic PCM dataset windows."""
import hashlib,json,math,os,sys,tempfile,wave
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from schemas.segmented_dataset import DatasetWorkerRequest,DatasetWorkerResult,DatasetErrorProtocol
from workers.audio_worker import FORMATS,MAX_SAMPLES,wav_frames

class MediaError(ValueError):
    def __init__(self,code,segment=None):self.code=code;self.segment=segment

def safe(path):
    path=Path(path).absolute()
    if path.resolve()!=path:raise ValueError('Unsafe private path')
    return path

def fingerprint(path):
    digest=hashlib.sha256();count=0
    with safe(path).open('rb') as reader:
        while True:
            chunk=reader.read(1024*1024)
            if not chunk:break
            count+=len(chunk)
            if count>50*1024*1024:raise MediaError('resource_limit')
            digest.update(chunk)
    if not count:raise MediaError('invalid_media')
    return digest.hexdigest()

def publish(path,data,limit=1024*1024):
    raw=json.dumps(data,ensure_ascii=False,allow_nan=False).encode('utf8')
    if len(raw)>limit:raise MediaError('resource_limit')
    temporary=None
    try:
        with tempfile.NamedTemporaryFile(dir=safe(path.parent),suffix='.tmp',delete=False) as writer:
            temporary=Path(writer.name);writer.write(raw);writer.flush();os.fsync(writer.fileno())
        os.replace(temporary,safe(path))
    finally:
        if temporary is not None:temporary.unlink(missing_ok=True)

def slice_audio(request,folder,av):
    import numpy as np
    source=safe(folder/('input'+Path(request.source_filename).suffix))
    if fingerprint(source)!=request.source_sha256:raise MediaError('changed_source')
    expected=wav_frames(source) if source.suffix=='.wav' else None
    audio=safe(folder/'audio');audio.mkdir(exist_ok=True)
    windows=[(round(row.start*32000),round(row.end*32000)) for row in request.windows]
    resampler=av.AudioResampler(format='s16',layout='mono',rate=32000)
    total=processed=frame_count=position=index=written=peak=0
    squares=0.0;rate=channels=None;writer=None;clips=[]
    def close_clip():
        nonlocal writer,index,written,peak,squares
        writer.close();writer=None
        first,last=windows[index]
        if written!=last-first:raise MediaError('source_window',index+1)
        if peak==0:raise MediaError('silence',index+1)
        rms=20*math.log10(math.sqrt(squares/written)/32768)
        warnings=[]
        if written<32000:warnings.append('short_clip')
        if written>320000:warnings.append('long_clip')
        if rms < -45:warnings.append('quiet_clip')
        if peak>=32760:warnings.append('clipping')
        path=safe(audio/f'segment_{index+1:04d}.wav')
        digest=hashlib.sha256()
        with path.open('rb') as reader:
            for chunk in iter(lambda:reader.read(65536),b''):digest.update(chunk)
        clips.append(dict(index=index+1,filename='audio/'+path.name,start_frame=first,end_frame=last,frames=written,
            duration_seconds=written/32000,sha256=digest.hexdigest(),peak=peak/32768,rms_dbfs=rms,warnings=warnings))
        index+=1;written=peak=0;squares=0.0
    def consume(frames):
        nonlocal processed,position,writer,written,peak,squares
        for frame in frames:
            processed+=frame.samples
            if processed>MAX_SAMPLES:raise MediaError('resource_limit')
            data=frame.to_ndarray().reshape(-1)
            while index<len(windows) and windows[index][0]<position+frame.samples:
                first,last=windows[index];begin=max(0,first-position);end=min(frame.samples,last-position)
                if end>begin:
                    if writer is None:
                        writer=wave.open(str(safe(audio/f'segment_{index+1:04d}.wav')),'wb');writer.setparams((1,2,32000,0,'NONE',''))
                    samples=data[begin:end].astype('<i2',copy=False)
                    writer.writeframesraw(samples.tobytes());written+=len(samples)
                    precise=samples.astype(np.float64);peak=max(peak,int(np.max(np.abs(precise))))
                    squares+=float(np.sum(precise*precise))
                if last<=position+frame.samples:close_clip()
                else:break
            position+=frame.samples
    try:
        with av.open(str(source),format=FORMATS[source.suffix.lstrip('.')],options={'protocol_whitelist':'file','enable_drefs':'0','use_absolute_path':'0','err_detect':'explode'}) as container:
            streams=list(container.streams.audio)
            if not streams:raise MediaError('invalid_media')
            for frame in container.decode(streams[0]):
                if frame.samples<=0:continue
                if not 8000<=frame.sample_rate<=192000 or not 1<=len(frame.layout.channels)<=8 or frame.samples>1048576:raise MediaError('resource_limit')
                if rate is None:rate,channels=frame.sample_rate,len(frame.layout.channels)
                if (rate,channels)!=(frame.sample_rate,len(frame.layout.channels)):raise MediaError('invalid_media')
                total+=frame.samples;processed+=frame.samples*channels;frame_count+=1
                if total/rate>1800 or processed>MAX_SAMPLES or frame_count>200000:raise MediaError('resource_limit')
                consume(resampler.resample(frame))
            consume(resampler.resample(None))
        if not total or rate is None or (expected is not None and expected!=total):raise MediaError('invalid_media')
        if index!=len(windows) or windows[-1][1]>position:raise MediaError('source_window',index+1)
        if fingerprint(source)!=request.source_sha256:raise MediaError('changed_source')
        return DatasetWorkerResult(task_id=request.task_id,run_nonce=request.run_nonce,source_sha256=request.source_sha256,
            source_duration_seconds=total/rate,clips=clips).model_dump()
    finally:
        if writer is not None:writer.close()

def execute(request_path):
    request=None;folder=None
    try:
        path=safe(request_path)
        if path.name!='request.json':return 2
        folder=safe(path.parent)
        with path.open('rb') as reader:raw=reader.read(256*1024+1)
        if len(raw)>256*1024:return 2
        request=DatasetWorkerRequest.model_validate(json.loads(raw),strict=True)
        if folder.name!='.staging-'+request.task_id:return 2
    except Exception:return 2
    try:
        import av
    except ImportError:return 3
    try:
        av.logging.set_level(av.logging.PANIC)
        result=slice_audio(request,folder,av);publish(folder/'worker-result.json',result)
        return 0
    except Exception as error:
        if isinstance(error,MediaError):code,segment=error.code,error.segment
        elif isinstance(error,OSError):code,segment='io_error',None
        else:code,segment='invalid_media',None
        try:publish(folder/'worker-error.json',DatasetErrorProtocol(task_id=request.task_id,run_nonce=request.run_nonce,code=code,segment=segment).model_dump(),1024)
        except Exception:return 4
        return 2

if __name__=='__main__':raise SystemExit(execute(Path(sys.argv[1])) if len(sys.argv)==2 else 2)
