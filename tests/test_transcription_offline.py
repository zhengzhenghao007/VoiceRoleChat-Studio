"""Offline transcription contract; fake lazy inference and isolated files."""
import asyncio
from concurrent.futures import ThreadPoolExecutor
import io
from pathlib import Path
import sys
import tempfile
import threading
import time
from types import SimpleNamespace
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'backend'))
from fastapi import HTTPException, UploadFile
from fastapi.testclient import TestClient
from app import app
from services import transcription_service as service
from api import transcriptions as api


def segment(start=0, end=1, text=' hello '):
    return SimpleNamespace(start=start, end=end, text=text)


class OfflineTranscriptionTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name); self.uploads=self.root/'uploads'; self.uploads.mkdir()
        self.results=self.root/'transcripts'; self.results.mkdir()
        self.filename='a'*32+'.wav'; (self.uploads/self.filename).write_bytes(b'fixture')
        for key,value in [('UPLOAD_DIR',self.uploads),('TRANSCRIPTS_DIR',self.results),('_model',None)]:
            change=patch.object(service,key,value); change.start(); self.addCleanup(change.stop)
        self.info=SimpleNamespace(language='en',language_probability=.98,duration=2.0)
        self.model=SimpleNamespace(transcribe=lambda *a,**k:(iter([segment()]),self.info))

    def transcribe(self, **kwargs):
        with patch.object(service,'get_whisper_model',return_value=self.model):
            return service.transcribe_audio(self.filename,**kwargs)

    def test_offline_constructor_and_missing_model_is_actionable_503(self):
        with patch.object(service,'WhisperModel',return_value=self.model) as loader:
            self.assertIs(service.get_whisper_model(),self.model)
            self.assertTrue(loader.call_args.kwargs['local_files_only'])
            self.assertIs(service.get_whisper_model(),self.model); self.assertEqual(loader.call_count,1)
        service._model=None
        with patch.object(service,'WhisperModel',side_effect=OSError('secret/path/token')):
            with self.assertRaises(HTTPException) as error: service.get_whisper_model()
            self.assertEqual(error.exception.status_code,503)
            self.assertNotIn('secret',error.exception.detail)
            self.assertIn('local',error.exception.detail.lower())

    def test_canonical_path_and_resolved_escape(self):
        for name in ('../x.wav','x.wav','A'*32+'.wav','a'*32+'.exe'):
            with self.assertRaises(HTTPException): service.validate_stored_filename(name)
        with patch.object(Path,'resolve',return_value=self.root/'outside.wav'):
            with self.assertRaises(HTTPException): service.validate_stored_filename(self.filename)

    def test_invalid_language_rejected_before_load(self):
        with patch.object(service,'get_whisper_model') as load:
            for language in ('zz','ja;token','JA',''):
                with self.assertRaises(HTTPException) as error: service.transcribe_audio(self.filename,language)
                self.assertEqual(error.exception.status_code,422)
            load.assert_not_called()

    def test_response_and_persisted_contract(self):
        result=self.transcribe(language='en')
        self.assertEqual(result['text'],'hello')
        self.assertEqual(result['transcript_file'],'transcripts/'+'a'*32+'.json')
        import json
        stored=json.loads((self.results/('a'*32+'.json')).read_text(encoding='utf8'))
        self.assertEqual(stored['segments'],[dict(start=0.0,end=1.0,text='hello')])
        self.assertEqual(list(self.results.glob('*.tmp')),[])

    def test_generator_failure_is_generic_and_preserves_previous(self):
        target=self.results/('a'*32+'.json'); target.write_bytes(b'previous')
        def broken():
            yield segment()
            raise RuntimeError('secret/path/token')
        self.model.transcribe=lambda *a,**k:(broken(),self.info)
        with self.assertRaises(HTTPException) as error: self.transcribe()
        self.assertEqual(error.exception.status_code,500)
        self.assertNotIn('secret',error.exception.detail)
        self.assertEqual(target.read_bytes(),b'previous')

    def test_invalid_times_never_published(self):
        for row in (segment(float('nan')),segment(-1),segment(1,0),segment(0,3)):
            self.model.transcribe=lambda *a,**k:(iter([row]),self.info)
            with self.assertRaises(HTTPException): self.transcribe()
            self.assertEqual(list(self.results.iterdir()),[])

    def test_atomic_failure_preserves_old_json_and_no_temp(self):
        target=self.results/('a'*32+'.json'); target.write_bytes(b'previous')
        with patch('os.replace',side_effect=OSError('disk')):
            with self.assertRaises(HTTPException): self.transcribe()
        self.assertEqual(target.read_bytes(),b'previous')
        self.assertEqual(list(self.results.glob('*.tmp')),[])

    def test_inference_lock_covers_lazy_segments(self):
        guard=threading.Lock(); active=0; maximum=0
        def lazy():
            nonlocal active,maximum
            with guard: active+=1; maximum=max(maximum,active)
            time.sleep(.03)
            yield segment()
            with guard: active-=1
        self.model.transcribe=lambda *a,**k:(lazy(),self.info)
        with patch.object(service,'get_whisper_model',return_value=self.model):
            with ThreadPoolExecutor(2) as pool: list(pool.map(lambda _:service.transcribe_audio(self.filename),range(2)))
        self.assertEqual(maximum,1)

    def test_upload_transcription_offloads_to_worker_thread(self):
        async def invoke():
            loop_thread=threading.get_ident()
            async def upload(file): return dict(stored_filename=self.filename)
            def inference(**kwargs): return dict(worker_thread=threading.get_ident())
            with patch.object(api,'save_uploaded_audio',side_effect=upload),patch.object(api,'transcribe_audio',side_effect=inference):
                result=await api.upload_and_transcribe(UploadFile(filename='x.wav',file=io.BytesIO(b'x')),language=None)
            self.assertNotEqual(result['worker_thread'],loop_thread)
        asyncio.run(invoke())

    def test_invalid_metadata_and_silent_timing_not_published(self):
        for field,value in [('duration',float('inf')),('duration',-1),
                            ('language_probability',float('nan')),('language_probability',1.1),
                            ('language','invalid')]:
            previous=getattr(self.info,field); setattr(self.info,field,value)
            with self.assertRaises(HTTPException): self.transcribe()
            setattr(self.info,field,previous)
        self.model.transcribe=lambda *a,**k:(iter([segment(0,3,' ')]),self.info)
        with self.assertRaises(HTTPException): self.transcribe()
        self.assertEqual(list(self.results.iterdir()),[])

    def test_backwards_segments_including_silence_preserve_previous(self):
        target=self.results/('a'*32+'.json');target.write_bytes(b'previous')
        for first,text in (('second','first'),('second',' '),(' ','first')):
            self.model.transcribe=lambda *a,**k:(iter([segment(1,1.5,first),segment(.5,1,text)]),self.info)
            with self.assertRaises(HTTPException) as error: self.transcribe()
            self.assertEqual(error.exception.status_code,500)
            self.assertEqual(target.read_bytes(),b'previous')
            self.assertEqual(list(self.results.glob('*.tmp')),[])
        self.model.transcribe=lambda *a,**k:(iter([segment(1,1.5),segment(1,1.7)]),self.info)
        self.assertEqual(len(self.transcribe()['segments']),2)

    def test_transcript_target_escape_preserves_external_file(self):
        external=self.root/'external.json';external.write_bytes(b'keep')
        target=self.results/('a'*32+'.json'); resolve=Path.resolve
        def escaped(path,*a,**k):
            return external if path == target else resolve(path,*a,**k)
        with patch.object(Path,'resolve',escaped):
            with self.assertRaises(HTTPException): self.transcribe()
        self.assertEqual(external.read_bytes(),b'keep')
        self.assertEqual(list(self.results.iterdir()),[])

    def test_api_and_dataset_consumer_compatibility(self):
        with TestClient(app) as client,patch.object(service,'get_whisper_model',return_value=self.model):
            response=client.post('/api/transcriptions',json=dict(stored_filename=self.filename,language='en'))
            self.assertEqual(response.status_code,200,response.text)
            self.assertEqual(response.json()['text'],'hello')
            invalid=client.post('/api/transcriptions',json=dict(stored_filename=self.filename,language='zz'))
            self.assertEqual(invalid.status_code,422)
        from services import dataset_service as consumer
        from schemas.dataset import DatasetBuildRequest
        characters=self.root/'characters';(characters/'actor').mkdir(parents=True)
        (characters/'actor'/'config.json').write_text('{"name":"actor"}',encoding='utf8')
        datasets=self.root/'datasets'
        with patch.object(consumer,'UPLOAD_DIR',self.uploads),patch.object(consumer,'TRANSCRIPTS_DIR',self.results),patch.object(consumer,'CHARACTERS_DIR',characters),patch.object(consumer,'DATASETS_DIR',datasets):
            result=consumer.build_gpt_sovits_dataset(DatasetBuildRequest(character_id='actor',
                stored_filename=self.filename,transcript_filename='a'*32+'.json',dataset_name='fixture'))
        self.assertEqual(result['entry_count'],1)
        self.assertIn('hello',(datasets/'fixture'/'transcript.list').read_text(encoding='utf8'))


if __name__=='__main__': unittest.main()
