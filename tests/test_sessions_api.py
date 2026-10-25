"""Session HTTP contract on isolated storage; no LLM or TTS dependencies called."""
import sys,tempfile,unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'backend'))
from fastapi import FastAPI
from fastapi.testclient import TestClient
from api import sessions
from schemas.character import CharacterResponse
from schemas.session import TurnInput
from services.character_service import CharacterError
from services.session_service import SessionService

class SessionAPITests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.store=SessionService(Path(self.temp.name)/'sessions')
        self.role=CharacterResponse(id='a'*32,name='Role',system_prompt='Be kind',created_at='2026-10-25')
        class Characters:
            def get(inner,identity):
                if identity!='a'*32:raise CharacterError('private path',404)
                return self.role
        app=FastAPI();app.include_router(sessions.router)
        app.dependency_overrides[sessions.get_session_service]=lambda:self.store
        app.dependency_overrides[sessions.get_character_service]=lambda:Characters()
        self.client=TestClient(app);self.addCleanup(self.client.close)
    def test_create_list_rename_messages_and_restart(self):
        self.assertEqual(self.client.get('/api/sessions').json(),{'items':[],'total':0});self.assertFalse(self.store.root.exists())
        result=self.client.post('/api/sessions',json={'character_id':'a'*32,'title':'test'});self.assertEqual(result.status_code,201,result.text)
        identity=result.json()['id'];self.role.system_prompt='changed'
        detail=self.client.get('/api/sessions/'+identity).json();self.assertEqual(detail['character']['system_prompt'],'Be kind')
        self.assertEqual(self.client.get('/api/sessions').json()['total'],1)
        self.assertEqual(self.client.patch('/api/sessions/'+identity,json={'title':'renamed','expected_revision':1}).status_code,200)
        self.assertEqual(self.client.patch('/api/sessions/'+identity,json={'title':'stale','expected_revision':1}).status_code,409)
        self.assertEqual(self.client.get('/api/sessions/'+identity+'/messages').json(),[])
        self.store.append_turn(identity,TurnInput(expected_revision=2,request_id='b'*32,user_text='hello',assistant_text='fixture'))
        messages=self.client.get('/api/sessions/'+identity+'/messages').json();self.assertEqual(len(messages),2)
        self.assertEqual(SessionService(self.store.root).get(identity).revision,3)
        self.assertEqual(self.client.post('/api/sessions/'+identity+'/messages',json={'role':'assistant','content':'untrusted'}).status_code,405)
    def test_invalid_character_and_schema_do_not_create_database(self):
        response=self.client.post('/api/sessions',json={'character_id':'c'*32,'title':'test'})
        self.assertEqual(response.status_code,404);self.assertNotIn('private path',response.text)
        for body in ({'character_id':'a'*32,'title':' '},{'character_id':'../x','title':'test'},{'character_id':'a'*32,'title':'test','system_prompt':'injected'}):
            self.assertEqual(self.client.post('/api/sessions',json=body).status_code,422)
        self.assertFalse(self.store.root.exists())
        self.assertEqual(self.client.get('/api/sessions?limit=101').status_code,422)
        self.assertEqual(self.client.get('/api/sessions/'+'d'*32).status_code,404)

if __name__=='__main__':unittest.main()
