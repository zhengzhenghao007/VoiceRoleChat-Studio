"""Owned async reply lifecycle. Only complete pairs survive process restart."""
import asyncio
from collections import OrderedDict
from starlette.concurrency import run_in_threadpool
from schemas.llm import Message,CompletionInput
from schemas.reply import ReplyRequest,ReplyState
from schemas.session import TurnInput
from services.llm_service import LLMError
from services.session_service import SessionError


class ReplyError(RuntimeError):
    def __init__(self,code,status_code=503):
        self.code=code;self.status_code=status_code;super().__init__(code)


class ReplyManager:
    def __init__(self,store,provider,*,history_limit=64):
        if type(history_limit) is not int or not 1<=history_limit<=64:raise ValueError('Invalid reply history limit')
        self.store=store;self.provider=provider;self.history_limit=history_limit
        self._jobs=OrderedDict();self._active=None;self._task=None;self.closing=False;self._cancelling=set()

    def _copy(self,state):return state.model_copy(deep=True)

    def _completed(self,identity,request_id,receipt):
        return ReplyState(session_id=identity,request_id=request_id,status='completed',receipt=receipt)

    async def _saved(self,identity,request_id):
        return await run_in_threadpool(self.store.lookup_turn,identity,request_id)

    def _context(self,session,history,user_text):
        system=session.character.system_prompt+'\nReply in '+session.character.reply_language+'.'
        if len(system)>8000 or len(system)+len(user_text)>16000:raise ReplyError('context_budget_exceeded',422)
        budget=len(system)+len(user_text);selected=[]
        for index in range(len(history)-2,-1,-2):
            pair=history[index:index+2]
            if len(pair)!=2 or [item.role for item in pair]!=['user','assistant']:raise ReplyError('context_invalid',409)
            size=sum(len(item.content) for item in pair)
            if len(selected)+4>40 or any(len(item.content)>8000 for item in pair) or budget+size>16000:break
            selected=pair+selected;budget+=size
        messages=[Message(role='system',content=system)]+[Message(role=item.role,content=item.content) for item in selected]+[Message(role='user',content=user_text)]
        return CompletionInput(messages=messages).messages

    async def begin(self,identity,request):
        if self.closing:raise ReplyError('reply_service_closed')
        request=ReplyRequest.model_validate(request.model_dump());key=(identity,request.request_id)
        saved=await self._saved(identity,request.request_id)
        if saved:
            receipt,text=saved
            if text!=request.user_text:raise ReplyError('request_conflict',409)
            return self._completed(identity,request.request_id,receipt)
        if key in self._jobs:
            original,state=self._jobs[key]
            if original.user_text!=request.user_text:raise ReplyError('request_conflict',409)
            return self._copy(state)
        session=await run_in_threadpool(self.store.get,identity)
        history=await run_in_threadpool(self.store.messages,identity)
        if session.revision!=request.expected_revision:raise ReplyError('revision_conflict',409)
        messages=self._context(session,history,request.user_text)
        # No suspension between final admission checks and taking ownership.
        if self.closing:raise ReplyError('reply_service_closed')
        if key in self._jobs:
            original,state=self._jobs[key]
            if original.user_text!=request.user_text:raise ReplyError('request_conflict',409)
            return self._copy(state)
        if self._active is not None:raise ReplyError('reply_busy',429)
        provider=self.provider()
        if not provider.settings.model:raise LLMError('model_not_configured')
        state=ReplyState(session_id=identity,request_id=request.request_id,status='generating')
        self._jobs[key]=(request,state)
        while len(self._jobs)>self.history_limit:self._jobs.popitem(last=False)
        self._active=key;self._task=asyncio.create_task(self._run(key,request,state,provider,messages))
        return self._copy(state)

    async def _run(self,key,request,state,provider,messages):
        try:
            text=await provider.complete(messages)
            if key in self._cancelling:state.status='cancelled';return
            state.status='committing'
            commit=asyncio.create_task(run_in_threadpool(self.store.append_turn,key[0],TurnInput(request_id=request.request_id,expected_revision=request.expected_revision,user_text=request.user_text,assistant_text=text,model=provider.settings.model)))
            try:receipt=await asyncio.shield(commit)
            except asyncio.CancelledError:receipt=await commit
            state.receipt=receipt;state.status='completed'
        except asyncio.CancelledError:state.status='cancelled'
        except (LLMError,SessionError,ReplyError) as error:state.status='failed';state.error_code=error.code
        except Exception:state.status='failed';state.error_code='reply_failed'
        finally:
            self._cancelling.discard(key)
            if self._active==key:self._active=None;self._task=None

    async def get(self,identity,request_id):
        saved=await self._saved(identity,request_id)
        if saved:return self._completed(identity,request_id,saved[0])
        job=self._jobs.get((identity,request_id))
        if job:return self._copy(job[1])
        raise ReplyError('reply_not_found',404)

    async def cancel(self,identity,request_id):
        key=(identity,request_id);job=self._jobs.get(key)
        if job is None:return await self.get(identity,request_id)
        state=job[1]
        if state.status=='committing':raise ReplyError('commit_in_progress',409)
        if state.status!='generating':return self._copy(state)
        task=self._task
        if task:
            if key not in self._cancelling:
                self._cancelling.add(key);task.cancel()
            try:await asyncio.shield(task)
            except asyncio.CancelledError:
                if task.done() and task.cancelled():state.status='cancelled'
                else:raise
        self._cancelling.discard(key)
        if self._active==key:self._active=None;self._task=None
        return self._copy(state)

    async def close(self):
        self.closing=True
        if self._active is None:return
        key=self._active;state=self._jobs[key][1];task=self._task
        if state.status=='committing' and task:await asyncio.shield(task)
        else:await self.cancel(*key)
