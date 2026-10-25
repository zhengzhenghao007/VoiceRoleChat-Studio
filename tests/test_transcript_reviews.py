"""Immutable raw transcripts and revision/hash-protected correction copies."""
from pathlib import Path
import hashlib,json,sys,tempfile,unittest
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'backend'))
from services.transcript_review_service import TranscriptReviews,ReviewError
from schemas.transcript_review import ReviewCreate,ReviewUpdate
from pydantic import ValidationError

class ReviewTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name);self.transcripts=self.root/'transcripts';self.transcripts.mkdir()
        self.uploads=self.root/'uploads';self.uploads.mkdir();self.identity='a'*32
        self.path=self.transcripts/(self.identity+'.json')
        self.raw=dict(stored_filename='b'*32+'.wav',language='ja',language_probability=1.0,duration=4.0,text='raw',segments=[dict(start=0.0,end=3.0,text='raw')],legacy_unknown={'keep':True})
        self.original=json.dumps(self.raw,ensure_ascii=False,indent=2).encode();self.path.write_bytes(self.original)
        self.service=TranscriptReviews(self.transcripts,self.uploads)
    def content(self,text=' corrected '):return dict(language='ja',segments=[dict(start=0,end=3,text=text)])
    def create(self):
        source=self.service.get(self.identity)
        return self.service.create(ReviewCreate(source_id=self.identity,expected_source_sha256=source['sha256'],**self.content()))
    def update(self,document,text='new'):
        return ReviewUpdate(expected_revision=document['revision'],expected_sha256=document['sha256'],**self.content(text))
    def test_legacy_read_is_readonly_and_orphan_audio_does_not_hide_text(self):
        before=self.path.stat().st_mtime_ns
        doc=self.service.get(self.identity);self.assertEqual(doc['kind'],'legacy');self.assertFalse(doc['editable'])
        self.assertEqual(doc['revision'],0);self.assertIsNone(doc['audio_url'])
        self.assertEqual(doc['transcript']['text'],'raw');self.assertEqual(self.service.list()['items'][0]['id'],self.identity)
        self.assertEqual(self.path.read_bytes(),self.original);self.assertEqual(self.path.stat().st_mtime_ns,before)
        self.assertFalse((self.transcripts/'.review_sources').exists())
    def test_copy_snapshot_and_revision_updates_preserve_raw_provenance(self):
        document=self.create();self.assertEqual(document['kind'],'review');self.assertEqual(document['revision'],1)
        self.assertEqual(document['transcript']['text'],'corrected');self.assertNotEqual(document['id'],self.identity)
        snapshot=self.transcripts/'.review_sources'/(hashlib.sha256(self.original).hexdigest()+'.json')
        self.assertEqual(snapshot.read_bytes(),self.original);self.assertEqual(self.path.read_bytes(),self.original)
        updated=self.service.update(document['id'],self.update(document))
        self.assertEqual(updated['revision'],2);self.assertEqual(updated['transcript']['text'],'new')
        self.assertEqual(updated['source_id'],self.identity);self.assertEqual(updated['created_at'],document['created_at'])
        self.assertEqual(self.path.read_bytes(),self.original)
    def test_stale_source_revision_and_external_hash_conflicts(self):
        source=self.service.get(self.identity);self.path.write_bytes(self.original+b' ')
        with self.assertRaises(ReviewError) as error:self.service.create(ReviewCreate(source_id=self.identity,expected_source_sha256=source['sha256'],**self.content()))
        self.assertEqual(error.exception.status_code,409)
        document=self.create();self.service.update(document['id'],self.update(document))
        with self.assertRaises(ReviewError) as error:self.service.update(document['id'],self.update(document))
        self.assertEqual(error.exception.status_code,409)
        latest=self.service.get(document['id']);path=self.transcripts/(document['id']+'.json');path.write_bytes(path.read_bytes()+b' ')
        with self.assertRaises(ReviewError):self.service.update(document['id'],self.update(latest))
    def test_invalid_review_content_and_immutable_raw_target(self):
        invalid=[[],[dict(start=0,end=1,text=' ')],[dict(start=2,end=1,text='bad')],[dict(start=float('nan'),end=1,text='bad')],
                 [dict(start=0,end=2,text='one'),dict(start=1,end=3,text='two')],[dict(start=0,end=5,text='long')]]
        source=self.service.get(self.identity)
        for segments in invalid:
            with self.assertRaises((ReviewError,ValidationError)):
                self.service.create(ReviewCreate(source_id=self.identity,expected_source_sha256=source['sha256'],language='ja',segments=segments))
        with self.assertRaises(ReviewError):self.service.create(ReviewCreate(source_id=self.identity,expected_source_sha256=source['sha256'],**dict(self.content(),language='zz')))
        with self.assertRaises(ReviewError):self.service.update(self.identity,ReviewUpdate(expected_revision=1,expected_sha256=source['sha256'],**self.content()))
        self.assertEqual(self.path.read_bytes(),self.original)
    def test_atomic_failure_preserves_review_and_temp_cleanup(self):
        document=self.create();path=self.transcripts/(document['id']+'.json');before=path.read_bytes()
        with patch('os.replace',side_effect=OSError('disk')):
            with self.assertRaises(ReviewError):self.service.update(document['id'],self.update(document))
        self.assertEqual(path.read_bytes(),before);self.assertEqual(list(self.transcripts.glob('*.tmp')),[])
    def test_bad_future_and_noncanonical_paths_are_diagnostic(self):
        (self.transcripts/('c'*32+'.json')).write_bytes(b'{')
        (self.transcripts/('d'*32+'.json')).write_text('{"schema_version":99}',encoding='utf8')
        self.assertEqual(len(self.service.list()['diagnostics']),2)
        for identity in ('../x','A'*32,'missing'):
            with self.assertRaises(ReviewError):self.service.get(identity)
        resolve=Path.resolve
        def escape(path,*a,**k):return self.root/'outside.json' if path==self.path else resolve(path,*a,**k)
        with patch.object(Path,'resolve',escape):
            with self.assertRaises(ReviewError):self.service.get(self.identity)
    def test_snapshot_dedup_and_corruption_never_overwrite(self):
        self.create();self.create();self.assertEqual(len(list((self.transcripts/'.review_sources').glob('*.json'))),1)
        snapshot=next((self.transcripts/'.review_sources').glob('*.json'));snapshot.write_bytes(b'bad')
        with self.assertRaises(ReviewError):self.create()
        self.assertEqual(snapshot.read_bytes(),b'bad')
    def test_job_source_is_readonly_and_result_remains_dataset_compatible(self):
        from services.transcription_job_service import read_json
        raw=dict(self.raw);raw.pop('legacy_unknown');raw.update(schema_version=2,id=self.identity,task_id=self.identity,run_nonce='e'*32,source_sha256='f'*64,revision=1,created_at='2026-10-25T00:00:00+00:00',transcript_file='transcripts/'+self.identity+'.json')
        self.path.write_text(json.dumps(raw),encoding='utf8');document=self.create()
        self.assertEqual(self.service.get(self.identity)['kind'],'job');self.assertFalse(self.service.get(self.identity)['editable'])
        saved=read_json(self.transcripts/(document['id']+'.json'));self.assertEqual(saved['language'],'ja');self.assertEqual(saved['text'],'corrected')

    def test_concurrent_store_instances_allow_only_one_revision(self):
        from concurrent.futures import ThreadPoolExecutor
        document=self.create();other=TranscriptReviews(self.transcripts,self.uploads)
        def edit(service):
            try:return service.update(document['id'],self.update(document))['revision']
            except ReviewError as error:return error.status_code
        with ThreadPoolExecutor(2) as pool:results=list(pool.map(edit,[self.service,other]))
        self.assertCountEqual(results,[2,409])

    def test_raw_overlap_can_be_read_and_corrected_and_failed_copy_leaves_only_snapshot(self):
        self.raw['segments']=[dict(start=0,end=2,text='one'),dict(start=1,end=3,text='two')]
        self.path.write_text(json.dumps(self.raw),encoding='utf8');doc=self.service.get(self.identity)
        self.assertEqual(len(doc['transcript']['segments']),2)
        from services import transcription_job_service as store
        replace=store.os.replace
        def fail_review(first,second):
            if Path(second).parent==self.transcripts:raise OSError('disk')
            return replace(first,second)
        before=self.path.read_bytes()
        with patch('os.replace',side_effect=fail_review):
            with self.assertRaises(ReviewError):self.create()
        self.assertEqual(self.path.read_bytes(),before)
        self.assertEqual(len(list(self.transcripts.glob('*.json'))),1)
        self.assertEqual(len(list((self.transcripts/'.review_sources').glob('*.json'))),1)

if __name__=='__main__':unittest.main()
