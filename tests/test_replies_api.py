"""Async HTTP reply/poll/cancel contract with deterministic fake inference."""
import asyncio,sys,unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'backend'))
import httpx
from fastapi import FastAPI
import test_sessions as fixtures
from test_replies import Provider
from api import replies
from services.reply_service import ReplyManager

class ReplyAPITests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.fixture=fixtures.SessionStorageTests();self.fixture.setUp();self.addCleanup(self.fixture.doCleanups)
        self.session=self.fixture.create();self.provider=Provider();self.manager=ReplyManager(self.fixture.store,lambda:self.provider)
        self.addAsyncCleanup(self.manager.close)
        app=FastAPI();app.include_router(replies.router);app.dependency_overrides[replies.get_reply_manager]=lambda:self.manager
        self.client=httpx.AsyncClient(transport=httpx.ASGITransport(app=app),base_url='http://studio');self.addAsyncCleanup(self.client.aclose)
        self.path='/api/sessions/'+self.session.id+'/replies'
    async def test_http_reply_poll_committed_replay(self):
        payload={'request_id':'b'*32,'expected_revision':1,'user_text':'hello'}
        response=await self.client.post(self.path,json=payload);self.assertEqual(response.status_code,202,response.text)
        if self.manager._task:await self.manager._task
        response=await self.client.get(self.path+'/'+'b'*32);self.assertEqual(response.status_code,200)
        self.assertEqual(response.json()['status'],'completed');receipt=response.json()['receipt']
        replay=await self.client.post(self.path,json=payload);self.assertEqual(replay.json()['receipt'],receipt)
        self.assertEqual(len(self.provider.calls),1)
        conflict=await self.client.post(self.path,json={**payload,'user_text':'different'});self.assertEqual(conflict.status_code,409)
    async def test_http_cancel_and_invalid_request(self):
        self.provider.release.clear();payload={'request_id':'c'*32,'expected_revision':1,'user_text':'hello'}
        self.assertEqual((await self.client.post(self.path,json=payload)).status_code,202);await self.provider.entered.wait()
        response=await self.client.post(self.path+'/'+'c'*32+'/cancel');self.assertEqual(response.status_code,202)
        self.assertEqual(response.json()['status'],'cancelled');self.assertTrue(self.provider.closed.is_set())
        self.assertEqual(self.fixture.store.messages(self.session.id),[])
        self.assertEqual((await self.client.post(self.path,json={**payload,'expected_revision':True})).status_code,422)
        self.assertEqual((await self.client.post(self.path,json={**payload,'base_url':'http://example.com'})).status_code,422)

if __name__=='__main__':unittest.main()
