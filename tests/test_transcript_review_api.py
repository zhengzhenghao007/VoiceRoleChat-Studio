"""Typed correction APIs and existing dataset consumer in temporary stores."""
from pathlib import Path
import json,sys,tempfile,unittest
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'backend'))
from fastapi.testclient import TestClient
from app import app
from api.transcriptions import get_reviews
from services.transcript_review_service import TranscriptReviews
from services import dataset_service
from schemas.dataset import DatasetBuildRequest

class ReviewAPITests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name);self.records=self.root/'transcripts';self.records.mkdir()
        self.uploads=self.root/'uploads';self.uploads.mkdir();self.identity='a'*32;self.name='b'*32+'.wav'
        (self.uploads/self.name).write_bytes(b'fixture')
        raw=dict(stored_filename=self.name,language='ja',language_probability=1.,duration=4.,text='raw',segments=[dict(start=0,end=3,text='raw')])
        (self.records/(self.identity+'.json')).write_text(json.dumps(raw),encoding='utf8')
        self.service=TranscriptReviews(self.records,self.uploads)
        app.dependency_overrides[get_reviews]=lambda:self.service;self.addCleanup(app.dependency_overrides.clear)
        self.client=TestClient(app);self.addCleanup(self.client.close)
    def body(self):
        doc=self.client.get('/api/transcriptions/records/'+self.identity).json()
        return dict(source_id=self.identity,expected_source_sha256=doc['sha256'],language='ja',segments=[dict(start=0,end=3,text='corrected')])
    def test_create_update_conflict_and_immutable_fields(self):
        self.assertEqual(self.client.get('/api/transcriptions/records').json()['items'][0]['kind'],'legacy')
        response=self.client.post('/api/transcriptions/reviews',json=self.body());self.assertEqual(response.status_code,201,response.text)
        doc=response.json();identity=doc['id']
        self.assertEqual(doc['audio_url'],'/api/voices/'+self.name+'/audio')
        update=dict(expected_revision=doc['revision'],expected_sha256=doc['sha256'],language='ja',segments=[dict(start=0,end=3,text='edited')])
        saved=self.client.patch('/api/transcriptions/reviews/'+identity,json=update);self.assertEqual(saved.status_code,200,saved.text)
        self.assertEqual(saved.json()['revision'],2)
        self.assertEqual(self.client.patch('/api/transcriptions/reviews/'+identity,json=update).status_code,409)
        update['duration']=10;self.assertEqual(self.client.patch('/api/transcriptions/reviews/'+identity,json=update).status_code,422)
        self.assertEqual(self.client.get('/api/transcriptions/reviews/'+self.identity).status_code,404)
    def test_validation_and_dataset_consumer(self):
        body=self.body();body['segments']=[dict(start=0,end=5,text='outside')]
        self.assertEqual(self.client.post('/api/transcriptions/reviews',json=body).status_code,422)
        response=self.client.post('/api/transcriptions/reviews',json=self.body());doc=response.json()
        characters=self.root/'characters';(characters/'actor').mkdir(parents=True)
        (characters/'actor'/'config.json').write_text('{"name":"actor"}',encoding='utf8')
        datasets=self.root/'datasets'
        with patch.object(dataset_service,'UPLOAD_DIR',self.uploads),patch.object(dataset_service,'TRANSCRIPTS_DIR',self.records),patch.object(dataset_service,'CHARACTERS_DIR',characters),patch.object(dataset_service,'DATASETS_DIR',datasets):
            result=dataset_service.build_gpt_sovits_dataset(DatasetBuildRequest(character_id='actor',stored_filename=self.name,transcript_filename=doc['id']+'.json',dataset_name='corrected'))
        self.assertEqual(result['entry_count'],1)
        self.assertIn('corrected',(datasets/'corrected'/'transcript.list').read_text(encoding='utf8'))

if __name__=='__main__':unittest.main()
