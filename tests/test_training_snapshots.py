"""Independent bounded training inputs; actual WAV fixtures, no ML commands."""
from pathlib import Path
import hashlib,json,os,sys,unittest
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'backend'))
import test_segmented_datasets as fixtures

class SnapshotTests(unittest.TestCase):
    def setUp(self):
        self.fixture=fixtures.SegmentedDatasetTests();self.fixture.setUp();self.addCleanup(self.fixture.doCleanups)
        f=self.fixture;self.data=f.service.build(f.request());self.source=f.service.root/'prepared'
        self.jobs=f.root/'jobs';self.jobs.mkdir();self.job='d'*32;self.work=self.jobs/self.job;self.work.mkdir()
    def snapshot(self):
        from services.training_snapshot import create_verified_training_snapshot
        return create_verified_training_snapshot(self.fixture.service.root,'prepared','actor',self.jobs,self.job)
    def test_independent_bytes_labels_and_provenance(self):
        (self.source/'unknown.bin').write_bytes(b'do not copy')
        result=self.snapshot();target=result[0]
        self.assertEqual(target,self.work/'inputs/prepared');self.assertFalse((target/'unknown.bin').exists())
        for relative in ['dataset.json','review.json','audio/segment_0001.wav','audio/segment_0002.wav']:
            self.assertEqual((target/relative).read_bytes(),(self.source/relative).read_bytes())
        self.assertTrue(all(row.startswith(str(target/'audio')) for row in result[2].read_text(encoding='utf8').splitlines()))
        provenance=json.loads((self.work/'input-provenance.json').read_bytes())
        self.assertEqual(provenance['job_id'],self.job)
        self.assertEqual(provenance['source_manifest_sha256'],hashlib.sha256((self.source/'dataset.json').read_bytes()).hexdigest())
        self.assertEqual(provenance['snapshot_relative_path'],'inputs/prepared')
        clip=target/'audio/segment_0001.wav';before=clip.read_bytes()
        (self.source/'audio/segment_0001.wav').write_bytes(b'changed source')
        self.assertEqual(clip.read_bytes(),before)
    def test_no_overwrite_and_invalid_identity(self):
        self.snapshot();marker=self.work/'inputs/prepared/keep';marker.write_bytes(b'keep')
        with self.assertRaises(Exception):self.snapshot()
        self.assertEqual(marker.read_bytes(),b'keep')
        from services.training_snapshot import create_verified_training_snapshot
        for job,name in [('../escape','prepared'),(self.job,'../prepared')]:
            with self.assertRaises(Exception):create_verified_training_snapshot(self.fixture.service.root,name,'actor',self.jobs,job)
    def test_copy_time_same_stat_mutation_rejected(self):
        from services import training_snapshot
        original=training_snapshot.copy_file;clip=self.source/'audio/segment_0001.wav';stamp=clip.stat()
        def mutate(source,target,*args,**kwargs):
            result=original(source,target,*args,**kwargs)
            if Path(source)==clip:
                data=bytearray(clip.read_bytes());data[-1]^=1;clip.write_bytes(data);os.utime(clip,ns=(stamp.st_atime_ns,stamp.st_mtime_ns))
            return result
        with patch.object(training_snapshot,'copy_file',mutate),self.assertRaises(Exception):self.snapshot()
        self.assertFalse((self.work/'input-provenance.json').exists())
    def test_partial_copy_preserved_without_success_marker(self):
        from services import training_snapshot
        original=training_snapshot.copy_file
        def failing(source,target,*args,**kwargs):
            if Path(source).name=='segment_0002.wav':raise OSError('injected copy failure')
            return original(source,target,*args,**kwargs)
        with patch.object(training_snapshot,'copy_file',failing),self.assertRaises(OSError):self.snapshot()
        self.assertTrue((self.work/'inputs/prepared/audio/segment_0001.wav').is_file())
        self.assertFalse((self.work/'input-provenance.json').exists())
    def test_copy_budget_and_no_overwrite(self):
        from services.training_snapshot import copy_file
        source=self.source/'review.json';target=self.work/'copy'
        with self.assertRaises(ValueError):copy_file(source,target,1,[100])
        target2=self.work/'keep';target2.write_bytes(b'keep')
        with self.assertRaises(FileExistsError):copy_file(source,target2,1024*1024,[128*1024*1024])
        self.assertEqual(target2.read_bytes(),b'keep')
        with self.assertRaises(ValueError):copy_file(source,self.work/'budget',1024*1024,[1])
    def test_invalid_source_never_publishes_provenance(self):
        (self.source/'review.json').write_bytes(b'bad')
        with self.assertRaises(Exception):self.snapshot()
        self.assertFalse((self.work/'input-provenance.json').exists())

if __name__=='__main__':unittest.main()
