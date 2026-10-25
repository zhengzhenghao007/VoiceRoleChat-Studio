"""Segment build HTTP and legacy safety contract, all directories temporary."""
from contextlib import ExitStack
from pathlib import Path
import json,sys,unittest
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'backend'))
from fastapi import HTTPException
from fastapi.testclient import TestClient
from app import app
from api.datasets import get_segmented
from services import dataset_service as legacy
from schemas.dataset import DatasetBuildRequest
import test_segmented_datasets as fixtures

class DatasetAPITests(unittest.TestCase):
    def setUp(self):
        self.fixture=fixtures.SegmentedDatasetTests();self.fixture.setUp();self.addCleanup(self.fixture.doCleanups)
        app.dependency_overrides[get_segmented]=lambda:self.fixture.service;self.addCleanup(app.dependency_overrides.clear)
        self.client=TestClient(app);self.addCleanup(self.client.close)
    def test_segment_build_list_detail_conflict_and_unknown_fields(self):
        body=self.fixture.request().model_dump()
        response=self.client.post('/api/datasets/segments',json=body);self.assertEqual(response.status_code,201,response.text)
        self.assertEqual(response.json()['entry_count'],2)
        self.assertEqual(self.client.get('/api/datasets').json()['items'][0]['dataset_name'],'prepared')
        self.assertEqual(self.client.get('/api/datasets/prepared').json()['schema_version'],2)
        self.assertEqual(self.client.post('/api/datasets/segments',json=body).status_code,409)
        body['source_path']='outside';self.assertEqual(self.client.post('/api/datasets/segments',json=body).status_code,422)
    def test_legacy_path_and_separator_guards(self):
        f=self.fixture
        with ExitStack() as stack:
            for key,value in [('UPLOAD_DIR',f.uploads),('TRANSCRIPTS_DIR',f.records),('CHARACTERS_DIR',f.characters),('DATASETS_DIR',f.service.root)]:stack.enter_context(patch.object(legacy,key,value))
            request=DatasetBuildRequest(character_id='actor',stored_filename=f.source.name,transcript_filename=f.review['id']+'.json',dataset_name='legacy')
            f.service.root.mkdir(exist_ok=True)
            result=legacy.build_gpt_sovits_dataset(request);self.assertEqual(result['entry_count'],1)
            outside=f.root/'outside';outside.mkdir();(outside/'config.json').write_text('{"name":"Outside"}',encoding='utf8')
            for character_id in ('../outside','../actor','..','actor/sub'):
                bad=request.model_copy(update={'character_id':character_id,'dataset_name':'bad'})
                with self.assertRaises(HTTPException):legacy.build_gpt_sovits_dataset(bad)
            path=f.records/(f.review['id']+'.json');data=json.loads(path.read_bytes());data['text']='bad|annotation';path.write_text(json.dumps(data),encoding='utf8')
            with self.assertRaises(HTTPException):legacy.build_gpt_sovits_dataset(request.model_copy(update={'dataset_name':'unsafe'}))
            self.assertFalse((f.service.root/'unsafe').exists())

if __name__=='__main__':unittest.main()
