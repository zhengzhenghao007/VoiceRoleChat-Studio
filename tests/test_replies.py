"""Reply lifecycle fixtures: no actual LLM, GPU or model files."""
import asyncio,sys,threading,unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
from uuid import uuid4
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'backend'))
import test_sessions as fixtures
from schemas.reply import ReplyRequest
from schemas.session import TurnInput
from services.llm_service import LLMError
from services.reply_service import ReplyManager,ReplyError

class Provider:
    def __init__(self):
        self.settings=SimpleNamespace(model='fixture');self.calls=[];self.entered=asyncio.Event();self.release=asyncio.Event();self.release.set();self.closed=asyncio.Event();self.error=None
    async def complete(self,messages):
        self.calls.append(messages);self.entered.set()
        try:
            await self.release.wait()
            if self.error:raise self.error
            return 'FAKE REPLY'
        finally:self.closed.set()

class ReplyTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.fixture=fixtures.SessionStorageTests();self.fixture.setUp();self.addCleanup(self.fixture.doCleanups)
        self.store=self.fixture.store;self.session=self.fixture.create();self.provider=Provider()
        self.manager=ReplyManager(self.store,lambda:self.provider);self.addAsyncCleanup(self.manager.close)
    def request(self,revision=1,identity=None,text='hello'):
        return ReplyRequest(request_id=identity or uuid4().hex,expected_revision=revision,user_text=text)
    async def settle(self):
        if self.manager._task:await asyncio.wait_for(asyncio.shield(self.manager._task),3)
    async def test_success_context_and_completed_replay_after_restart(self):
        request=self.request();result=await self.manager.begin(self.session.id,request)
        self.assertEqual(result.status,'generating');await self.settle()
        result=await self.manager.get(self.session.id,request.request_id);self.assertEqual(result.status,'completed')
        self.assertEqual(len(self.store.messages(self.session.id)),2)
        system=self.provider.calls[0][0].content;self.assertIn('Be concise',system);self.assertIn('Japanese',system)
        def unavailable():raise LLMError('configuration_invalid')
        restored=ReplyManager(self.store,unavailable);self.addAsyncCleanup(restored.close)
        replay=await restored.begin(self.session.id,request);self.assertEqual(replay.receipt,result.receipt)
        self.assertEqual((await restored.get(self.session.id,request.request_id)).status,'completed')
        with self.assertRaises(ReplyError) as conflict:await restored.begin(self.session.id,request.model_copy(update={'user_text':'different'}))
        self.assertEqual(conflict.exception.code,'request_conflict')
    async def test_cancel_and_concurrent_retry_never_append_or_regenerate(self):
        self.provider.release.clear();request=self.request()
        await self.manager.begin(self.session.id,request);await self.provider.entered.wait()
        same=await self.manager.begin(self.session.id,request);self.assertEqual(same.status,'generating')
        with self.assertRaises(ReplyError) as busy:await self.manager.begin(self.session.id,self.request())
        self.assertEqual(busy.exception.status_code,429)
        result=await self.manager.cancel(self.session.id,request.request_id)
        self.assertEqual(result.status,'cancelled');self.assertTrue(self.provider.closed.is_set())
        self.assertEqual(self.store.messages(self.session.id),[]);self.assertEqual(len(self.provider.calls),1)
        self.assertEqual((await self.manager.begin(self.session.id,request)).status,'cancelled')
    async def test_failure_and_stale_revision_commit_no_partial_pair(self):
        self.provider.error=LLMError('authentication_failed');request=self.request()
        await self.manager.begin(self.session.id,request);await self.settle()
        result=await self.manager.get(self.session.id,request.request_id);self.assertEqual(result.error_code,'authentication_failed')
        self.assertEqual(self.store.messages(self.session.id),[])
        self.provider.error=None;self.provider.release.clear();self.provider.entered.clear();request=self.request()
        await self.manager.begin(self.session.id,request);await self.provider.entered.wait()
        from schemas.session import SessionRename
        self.store.rename(self.session.id,SessionRename(title='changed',expected_revision=1))
        self.provider.release.set();await self.settle()
        result=await self.manager.get(self.session.id,request.request_id);self.assertEqual(result.error_code,'revision_conflict')
        self.assertEqual(self.store.messages(self.session.id),[])
    async def test_commit_phase_rejects_cancel_and_shutdown_waits(self):
        entered=threading.Event();release=threading.Event();original=self.store.append_turn
        def delayed(*args):entered.set();release.wait(2);return original(*args)
        request=self.request()
        with patch.object(self.store,'append_turn',delayed):
            await self.manager.begin(self.session.id,request)
            while not entered.is_set():await asyncio.sleep(.01)
            try:
                with self.assertRaises(ReplyError) as commit:await self.manager.cancel(self.session.id,request.request_id)
                self.assertEqual(commit.exception.code,'commit_in_progress')
                closing=asyncio.create_task(self.manager.close());await asyncio.sleep(.03);self.assertFalse(closing.done())
            finally:release.set()
            await closing
        self.assertEqual((await self.manager.get(self.session.id,request.request_id)).status,'completed')
        self.assertEqual(len(self.store.messages(self.session.id)),2)
    async def test_context_trims_whole_pairs_and_rejects_oversized_system(self):
        for revision in range(1,4):self.store.append_turn(self.session.id,TurnInput(expected_revision=revision,request_id=uuid4().hex,user_text=str(revision)*4000,assistant_text='a'*4000))
        request=self.request(revision=4);await self.manager.begin(self.session.id,request);await self.settle()
        messages=self.provider.calls[-1];self.assertEqual([m.role for m in messages],['system','user','assistant','user'])
        self.assertTrue(messages[1].content.startswith('3'));self.assertLessEqual(sum(len(m.content) for m in messages),16000)
        role=self.fixture.character.model_copy(update={'system_prompt':'x'*8001})
        from schemas.session import SessionCreate
        session=self.store.create(SessionCreate(character_id='a'*32,title='large'),role)
        with self.assertRaises(ReplyError) as budget:await self.manager.begin(session.id,self.request())
        self.assertEqual(budget.exception.code,'context_budget_exceeded');self.assertEqual(len(self.provider.calls),1)
    async def test_missing_model_and_close_admission(self):
        self.provider.settings.model=''
        with self.assertRaises(LLMError):await self.manager.begin(self.session.id,self.request())
        self.assertFalse(self.manager._task);await self.manager.close()
        with self.assertRaises(ReplyError) as closed:await self.manager.begin(self.session.id,self.request())
        self.assertEqual(closed.exception.code,'reply_service_closed')
    async def test_disconnected_cancel_waiter_does_not_interrupt_owned_cleanup(self):
        cleanup=asyncio.Event();permit=asyncio.Event();closed=asyncio.Event()
        async def complete(messages):
            self.provider.entered.set()
            try:await asyncio.Event().wait()
            finally:cleanup.set();await permit.wait();closed.set()
        self.provider.complete=complete;request=self.request()
        await self.manager.begin(self.session.id,request);await self.provider.entered.wait()
        first=asyncio.create_task(self.manager.cancel(self.session.id,request.request_id));await cleanup.wait()
        first.cancel()
        with self.assertRaises(asyncio.CancelledError):await first
        self.assertFalse(closed.is_set());self.assertEqual(self.manager._jobs[(self.session.id,request.request_id)][1].status,'generating')
        second=asyncio.create_task(self.manager.cancel(self.session.id,request.request_id));await asyncio.sleep(.02)
        self.assertFalse(second.done());permit.set();result=await second
        self.assertEqual(result.status,'cancelled');self.assertTrue(closed.is_set());self.assertEqual(self.store.messages(self.session.id),[])
    async def test_cancel_before_worker_starts_and_suppressed_cancel(self):
        request=self.request();await self.manager.begin(self.session.id,request)
        self.assertEqual((await self.manager.cancel(self.session.id,request.request_id)).status,'cancelled')
        self.provider.entered.clear()
        async def ignoring(messages):
            self.provider.entered.set()
            try:await asyncio.Event().wait()
            except asyncio.CancelledError:return 'ignored cancellation'
        self.provider.complete=ignoring;request=self.request()
        await self.manager.begin(self.session.id,request);await self.provider.entered.wait()
        self.assertEqual((await self.manager.cancel(self.session.id,request.request_id)).status,'cancelled')
        self.assertEqual(self.store.messages(self.session.id),[])
    async def test_history_bound_and_message_count_budget(self):
        self.manager.history_limit=2;self.provider.error=LLMError('provider_unavailable');ids=[]
        for _ in range(3):
            request=self.request();ids.append(request.request_id);await self.manager.begin(self.session.id,request);await self.settle()
        self.assertEqual(len(self.manager._jobs),2)
        with self.assertRaises(ReplyError) as forgotten:await self.manager.get(self.session.id,ids[0])
        self.assertEqual(forgotten.exception.status_code,404)
        history=[]
        for index in range(21):history.extend([SimpleNamespace(role='user',content=str(index)),SimpleNamespace(role='assistant',content='reply')])
        messages=self.manager._context(self.session,history,'new')
        self.assertEqual(len(messages),40);self.assertEqual(messages[-1].content,'new');self.assertEqual(messages[1].content,'2')
    async def test_backend_shutdown_closes_reply_admission_first(self):
        import app as backend
        from contextlib import ExitStack
        calls=[]
        async def close_reply():calls.append('reply')
        with ExitStack() as stack:
            stack.enter_context(patch.object(backend,'start_training_commands'))
            stack.enter_context(patch.object(backend,'start_training_queue'))
            stack.enter_context(patch.object(backend,'close_reply_manager',close_reply))
            for name in ('close_training_queue','close_training_commands','close_jobs','cleanup_retained','close_tts_service'):
                stack.enter_context(patch.object(backend,name,lambda name=name:calls.append(name)))
            async with backend.lifespan(backend.app):pass
        self.assertEqual(calls[0],'reply')

if __name__=='__main__':unittest.main()
