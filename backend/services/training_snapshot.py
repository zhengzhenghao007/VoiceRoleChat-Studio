"""Private training input copies, bounded and verified before provenance commit."""
import hashlib,json,re
from pathlib import Path
from services.training_dataset import component,exclusive_directory,validate_prepared_dataset
from services.transcription_job_service import safe,atomic_json,now
from services.segmented_dataset_service import label

TOTAL_LIMIT=128*1024*1024

def bounded_bytes(path,limit):
    with safe(path).open('rb') as reader:data=reader.read(limit+1)
    if len(data)>limit:raise ValueError('Snapshot metadata limit exceeded')
    return data

def copy_file(source,target,limit,budget):
    source=safe(source);target=safe(target)
    if source.stat().st_size>limit:raise ValueError('Input exceeds snapshot file limit')
    digest=hashlib.sha256();count=0
    with source.open('rb') as reader,target.open('xb') as writer:
        while True:
            block=reader.read(1024*1024)
            if not block:break
            count+=len(block)
            if count>limit or len(block)>budget[0]:raise ValueError('Snapshot byte budget exceeded')
            writer.write(block);digest.update(block);budget[0]-=len(block)
        writer.flush()
    return digest.hexdigest()

def create_verified_training_snapshot(dataset_root,name,character_id,jobs_root,job_id):
    if not re.fullmatch(r'[0-9a-f]{32}',job_id):raise ValueError('Invalid training job ID')
    work=component(jobs_root,job_id)
    if not work.is_dir():raise ValueError('Training work directory must already be owned')
    source,_,_,metadata=validate_prepared_dataset(dataset_root,name,character_id)
    source_manifest=bounded_bytes(source/'dataset.json',1024*1024)
    manifest_hash=hashlib.sha256(source_manifest).hexdigest()
    inputs=exclusive_directory(work,'inputs');target=exclusive_directory(inputs,name)
    audio=exclusive_directory(target,'audio');budget=[TOTAL_LIMIT]
    if copy_file(source/'dataset.json',target/'dataset.json',1024*1024,budget)!=manifest_hash:raise ValueError('Manifest changed during copy')
    if copy_file(source/'review.json',target/'review.json',8*1024*1024,budget)!=metadata['review_sha256']:raise ValueError('Review changed during copy')
    rows=[]
    for clip in metadata['clips']:
        path=target/clip['filename']
        if copy_file(source/clip['filename'],path,44+960000*2,budget)!=clip['sha256']:raise ValueError('Clip changed during copy')
        rows.append(f"{label(str(path))}|{label(metadata['speaker_name'])}|{metadata['language']}|{label(clip['text'])}")
    annotation=('\n'.join(rows)+'\n').encode('utf8')
    if len(annotation)>8*1024*1024 or len(annotation)>budget[0]:raise ValueError('Annotation byte budget exceeded')
    with safe(target/'transcript.list').open('xb') as writer:writer.write(annotation)
    budget[0]-=len(annotation)
    # Recheck source bytes through the original integrity contract before commit.
    validate_prepared_dataset(dataset_root,name,character_id)
    if bounded_bytes(source/'dataset.json',1024*1024)!=source_manifest:raise ValueError('Source manifest changed')
    result=validate_prepared_dataset(inputs,name,character_id)
    provenance=dict(schema_version=1,job_id=job_id,source_dataset_name=name,
        source_manifest_sha256=manifest_hash,source_review_sha256=metadata['review_sha256'],
        snapshot_relative_path='inputs/'+name,entry_count=metadata['entry_count'],
        total_duration=metadata['total_duration'],created_at=now(),
        clips=[dict(filename=c['filename'],sha256=c['sha256'],frames=c['frames']) for c in metadata['clips']])
    if len(json.dumps(provenance,ensure_ascii=False).encode('utf8'))>budget[0]:raise ValueError('Provenance byte budget exceeded')
    path=safe(work/'input-provenance.json')
    with path.open('xb'):
        pass
    atomic_json(path,provenance,1024*1024)
    return (*result[:3],dict(result[3],training_input_provenance=provenance))
