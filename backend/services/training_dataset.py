"""Strict read-only integrity checks for already published segmented datasets."""
import re,wave
from pathlib import Path
from services.transcription_job_service import safe,read_json
from services.segmented_dataset_service import label,digest_file
from schemas.segmented_dataset import SegmentDatasetManifest,SegmentDatasetRequest

def component(root,name):
    if not isinstance(name,str) or not re.fullmatch(r'[A-Za-z0-9_-]{1,100}',name):raise ValueError('Invalid training storage identity')
    SegmentDatasetRequest.normal_directory(name)
    return safe(safe(root)/name)

def exclusive_directory(root,name):
    path=component(root,name)
    path.parent.mkdir(parents=True,exist_ok=True)
    path.mkdir(exist_ok=False)
    return path

def validate_prepared_dataset(root,name,character_id):
    folder=component(root,name)
    manifest=SegmentDatasetManifest.model_validate(read_json(safe(folder/'dataset.json'),1024*1024),strict=True)
    if manifest.dataset_name!=name or manifest.character_id!=character_id:raise ValueError('Dataset identity mismatch')
    if manifest.entry_count!=len(manifest.clips):raise ValueError('Dataset entry count mismatch')
    if manifest.annotation_file!=f'datasets/{name}/transcript.list' or manifest.source_transcript_snapshot!=f'datasets/{name}/review.json':raise ValueError('Dataset metadata path mismatch')
    if digest_file(folder/'review.json',8*1024*1024)!=manifest.review_sha256:raise ValueError('Review snapshot hash mismatch')
    speaker=label(manifest.speaker_name);rows=[];total=0;previous=0
    for index,clip in enumerate(manifest.clips,1):
        if clip.index!=index or clip.filename!=f'audio/segment_{index:04d}.wav':raise ValueError('Dataset clip identity mismatch')
        if clip.start_frame<previous or clip.end_frame-clip.start_frame!=clip.frames:raise ValueError('Dataset frame window mismatch')
        if round(clip.start_seconds*32000)!=clip.start_frame or round(clip.end_seconds*32000)!=clip.end_frame:raise ValueError('Dataset timestamp mismatch')
        if clip.duration_seconds!=clip.frames/32000:raise ValueError('Dataset clip duration mismatch')
        previous=clip.end_frame;path=safe(folder/clip.filename)
        if path.stat().st_size!=44+clip.frames*2:raise ValueError('Unexpected clip size')
        if digest_file(path,1920044)!=clip.sha256:raise ValueError('Clip SHA256 mismatch')
        with wave.open(str(path),'rb') as audio:
            if (audio.getnchannels(),audio.getsampwidth(),audio.getframerate(),audio.getnframes(),audio.getcomptype())!=(1,2,32000,clip.frames,'NONE'):raise ValueError('Invalid clip PCM')
            if len(audio.readframes(clip.frames))!=clip.frames*2:raise ValueError('Incomplete clip PCM')
        rows.append(f'{label(str(path))}|{speaker}|{manifest.language}|{label(clip.text)}')
        total+=clip.frames
    if abs(total/32000-manifest.total_duration)>1e-9:raise ValueError('Dataset total duration mismatch')
    annotation=safe(folder/'transcript.list')
    with annotation.open('rb') as reader:content=reader.read(8*1024*1024+1)
    if len(content)>8*1024*1024 or content.decode('utf8')!='\n'.join(rows)+'\n':raise ValueError('Annotation mismatch')
    return folder,safe(folder/'audio'),annotation,manifest.model_dump()
