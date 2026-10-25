"""Bounded local compatible HTTP client. No startup traffic or model installation."""
import asyncio,json,math,os,re
from dataclasses import dataclass,field
from urllib.parse import urlsplit
import httpx
from pydantic import ValidationError
from schemas.llm import CompletionInput,LLMConfiguration


ERRORS={
    'configuration_invalid':503,'model_not_configured':503,'provider_unavailable':503,
    'authentication_failed':503,'model_unavailable':503,'provider_timeout':504,
    'provider_busy':429,'provider_error':502,'invalid_response':502,'response_too_large':502,
    'invalid_messages':422,
}


class LLMError(RuntimeError):
    def __init__(self,code):
        self.code=code;self.status_code=ERRORS[code]
        super().__init__(code)


def model_name(value):
    return isinstance(value,str) and 0<len(value)<=200 and value==value.strip() and not any(ord(c)<33 or ord(c)==127 for c in value)


@dataclass(frozen=True)
class LLMSettings:
    base_url:str=field(repr=False)
    model:str
    key:str=field(repr=False)
    timeout:float=30
    max_tokens:int=128

    @classmethod
    def load(cls,environment=None):
        env=os.environ if environment is None else environment
        try:
            raw=env.get('LLM_BASE_URL','http://127.0.0.1:11434/v1')
            if not isinstance(raw,str) or len(raw)>2048 or any(ord(c)<=32 or ord(c)==127 for c in raw):raise ValueError()
            url=urlsplit(raw)
            if url.scheme!='http' or url.hostname not in ('localhost','127.0.0.1','::1') or url.username is not None or url.password is not None or url.query or url.fragment or url.path not in ('/v1','/v1/'):raise ValueError()
            port=url.port if url.port is not None else 80
            if not 1<=port<=65535 or '?' in raw or '#' in raw:raise ValueError()
            # Pin localhost to a literal address: never resolve a configurable name.
            host='[::1]' if url.hostname=='::1' else '127.0.0.1'
            base=f'http://{host}:{port}/v1'
            model=env.get('LLM_MODEL','').strip()
            if model and not model_name(model):raise ValueError()
            key=env.get('LLM_API_KEY','')
            if len(key)>4096 or any(ord(c)<33 or ord(c)>126 for c in key):raise ValueError()
            timeout=float(env.get('LLM_REQUEST_TIMEOUT','30'))
            if not math.isfinite(timeout) or not 1<=timeout<=120:raise ValueError()
            tokens=env.get('LLM_MAX_TOKENS','128')
            if not re.fullmatch(r'[0-9]{1,4}',tokens) or not 1<=int(tokens)<=2048:raise ValueError()
            return cls(base,model,key,timeout,int(tokens))
        except (ValueError,TypeError,AttributeError):raise LLMError('configuration_invalid') from None


class LLMService:
    def __init__(self,settings,*,transport=None):
        self.settings=settings;self.transport=transport;self.busy=False

    def configuration(self):
        return LLMConfiguration(configured=bool(self.settings.model),model=self.settings.model or None,
            credential_configured=bool(self.settings.key),error_code=None if self.settings.model else 'model_not_configured')

    async def _request(self,method,path,payload=None):
        if self.busy:raise LLMError('provider_busy')
        self.busy=True
        try:
            loop=asyncio.get_running_loop();deadline=loop.time()+self.settings.timeout
            result=await asyncio.wait_for(self._exchange(method,path,payload),timeout=self.settings.timeout)
            # Bounded synchronous parsing cannot be preempted, so check again before accepting.
            if loop.time()>=deadline:raise LLMError('provider_timeout')
            return result
        except (asyncio.TimeoutError,httpx.TimeoutException):raise LLMError('provider_timeout') from None
        except httpx.RequestError:raise LLMError('provider_unavailable') from None
        finally:self.busy=False

    async def _exchange(self,method,path,payload):
        headers={'Accept':'application/json','Accept-Encoding':'identity'}
        if self.settings.key:headers['Authorization']='Bearer '+self.settings.key
        async with httpx.AsyncClient(timeout=self.settings.timeout,trust_env=False,follow_redirects=False,transport=self.transport) as client:
            async with client.stream(method,self.settings.base_url+path,json=payload,headers=headers) as response:
                status=response.status_code
                if status in (401,403):raise LLMError('authentication_failed')
                if status==404 and method=='POST':raise LLMError('model_unavailable')
                if status==429:raise LLMError('provider_busy')
                if status!=200:raise LLMError('provider_error')
                if response.headers.get('content-encoding','identity').lower()!='identity':raise LLMError('invalid_response')
                body=bytearray()
                # MockTransport may supply prebuffered content; production streams raw bytes.
                if response.is_stream_consumed:
                    if len(response.content)>262144:raise LLMError('response_too_large')
                    body.extend(response.content)
                else:
                    async for chunk in response.aiter_raw():
                        if len(body)+len(chunk)>262144:raise LLMError('response_too_large')
                        body.extend(chunk)
                try:
                    data=json.loads(body)
                    if not isinstance(data,dict):raise ValueError()
                    return data
                except (ValueError,UnicodeError,RecursionError):raise LLMError('invalid_response') from None

    async def models(self):
        data=await self._request('GET','/models')
        entries=data.get('data')
        if not isinstance(entries,list) or len(entries)>1000:raise LLMError('invalid_response')
        if any(not isinstance(item,dict) or not model_name(item.get('id')) for item in entries):raise LLMError('invalid_response')
        return sorted({item['id'] for item in entries})

    async def complete(self,messages):
        if not self.settings.model:raise LLMError('model_not_configured')
        try:validated=CompletionInput(messages=messages)
        except ValidationError:raise LLMError('invalid_messages') from None
        payload=dict(model=self.settings.model,messages=[item.model_dump() for item in validated.messages],stream=False,max_tokens=self.settings.max_tokens)
        data=await self._request('POST','/chat/completions',payload)
        try:
            choices=data['choices']
            if not isinstance(choices,list) or len(choices)!=1:raise ValueError()
            message=choices[0]['message'];content=message['content']
            if message.get('role')!='assistant' or message.get('tool_calls') or not isinstance(content,str) or not content.strip() or len(content)>16000:raise ValueError()
            return content
        except (KeyError,TypeError,ValueError,IndexError):raise LLMError('invalid_response') from None
