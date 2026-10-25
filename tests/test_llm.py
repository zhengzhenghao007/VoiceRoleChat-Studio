"""Local provider contract; responses are fixtures, never real LLM output."""
import asyncio,json,sys,unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'backend'))
import httpx
from services.llm_service import LLMSettings,LLMService,LLMError
from schemas.llm import Message

class LLMTests(unittest.IsolatedAsyncioTestCase):
    def settings(self,**values):
        return LLMSettings.load({'LLM_MODEL':'fixture',**values})
    def test_local_configuration_and_secret_repr(self):
        settings=self.settings(LLM_API_KEY='SECRET')
        self.assertNotIn('SECRET',repr(settings));self.assertEqual(settings.timeout,30)
        for url in ('http://example.com/v1','https://127.0.0.1/v1','http://a:b@localhost/v1','http://localhost/v1?q=SECRET','http://localhost/v1#x','http://127.0.0.1/v1/../admin','http://localhost:0/v1'):
            with self.subTest(url=url),self.assertRaises(LLMError):self.settings(LLM_BASE_URL=url)
        for values in ({'LLM_REQUEST_TIMEOUT':'nan'},{'LLM_REQUEST_TIMEOUT':'121'},{'LLM_MAX_TOKENS':'0'},{'LLM_MAX_TOKENS':'1.5'},{'LLM_MODEL':'x\ny'}):
            with self.subTest(values=values),self.assertRaises(LLMError):self.settings(**values)
    async def test_models_and_completion_payload(self):
        requests=[]
        def handler(request):
            requests.append(request)
            if request.method=='GET':return httpx.Response(200,json={'data':[{'id':'fixture'},{'id':'fixture'}]})
            return httpx.Response(200,json={'choices':[{'message':{'role':'assistant','content':'fixture reply'},'finish_reason':'stop'}]})
        service=LLMService(self.settings(LLM_API_KEY='SECRET'),transport=httpx.MockTransport(handler))
        self.assertEqual(await service.models(),['fixture'])
        self.assertEqual(await service.complete([Message(role='user',content='hello')]),'fixture reply')
        payload=json.loads(requests[-1].content);self.assertFalse(payload['stream']);self.assertEqual(payload['max_tokens'],128)
        self.assertEqual(requests[-1].headers['authorization'],'Bearer SECRET')
    async def test_fixed_error_codes_no_upstream_error_echo(self):
        for status,code in ((401,'authentication_failed'),(403,'authentication_failed'),(404,'model_unavailable'),(429,'provider_busy'),(500,'provider_error'),(302,'provider_error')):
            transport=httpx.MockTransport(lambda request:httpx.Response(status,text='SECRET',headers={'location':'http://example.com'}))
            with self.subTest(status=status),self.assertRaises(LLMError) as context:
                await LLMService(self.settings(),transport=transport).complete([Message(role='user',content='x')])
            self.assertEqual(context.exception.code,code);self.assertNotIn('SECRET',str(context.exception))
    async def test_bounded_invalid_and_encoded_responses(self):
        responses=[httpx.Response(200,content=b'x'*262145),httpx.Response(200,text='bad json'),httpx.Response(200,json={'choices':[]}),httpx.Response(200,json={'choices':[{'message':{'content':'x'*16001}}]}),httpx.Response(200,headers={'content-encoding':'br'},content=b'bad')]
        for response in responses:
            with self.subTest(response=response),self.assertRaises(LLMError):
                await LLMService(self.settings(),transport=httpx.MockTransport(lambda request:response)).complete([Message(role='user',content='x')])
    async def test_total_deadline_and_concurrency_release(self):
        entered=asyncio.Event()
        async def slow(request):entered.set();await asyncio.sleep(3);return httpx.Response(200,json={'data':[]})
        service=LLMService(self.settings(LLM_REQUEST_TIMEOUT='1'),transport=httpx.MockTransport(slow))
        task=asyncio.create_task(service.models());await entered.wait()
        with self.assertRaises(LLMError) as busy:await service.models()
        self.assertEqual(busy.exception.code,'provider_busy')
        with self.assertRaises(LLMError) as timeout:await task
        self.assertEqual(timeout.exception.code,'provider_timeout');self.assertFalse(service.busy)
    async def test_missing_model_and_network_unavailable(self):
        async def offline(request):raise httpx.ConnectError('SECRET')
        service=LLMService(LLMSettings.load({}),transport=httpx.MockTransport(offline))
        with self.assertRaises(LLMError) as missing:await service.complete([Message(role='user',content='x')])
        self.assertEqual(missing.exception.code,'model_not_configured')
        with self.assertRaises(LLMError) as unavailable:await service.models()
        self.assertEqual(unavailable.exception.code,'provider_unavailable')
    async def test_cancel_releases_admission_and_closes_response(self):
        entered=asyncio.Event();closed=asyncio.Event()
        class SlowStream(httpx.AsyncByteStream):
            async def __aiter__(self):
                entered.set();await asyncio.sleep(30);yield b'{}'
            async def aclose(self):closed.set()
        service=LLMService(self.settings(),transport=httpx.MockTransport(lambda request:httpx.Response(200,stream=SlowStream())))
        task=asyncio.create_task(service.models());await entered.wait();task.cancel()
        with self.assertRaises(asyncio.CancelledError):await task
        self.assertTrue(closed.is_set());self.assertFalse(service.busy)
    async def test_protocol_rejects_invalid_models_and_message_content(self):
        for data in ({'data':[{'id':'x\ny'}]},{'data':[{'id':'fixture'}]*1001},{'data':{}},{}):
            with self.subTest(data_type='models'),self.assertRaises(LLMError):
                await LLMService(self.settings(),transport=httpx.MockTransport(lambda request:httpx.Response(200,json=data))).models()
        for message in ({},{'role':'assistant','content':None},{'role':'assistant','content':123},{'role':'assistant','content':'x','tool_calls':[{}]}):
            with self.subTest(message=message),self.assertRaises(LLMError):
                await LLMService(self.settings(),transport=httpx.MockTransport(lambda request:httpx.Response(200,json={'choices':[{'message':message}]}))).complete([Message(role='user',content='x')])

if __name__=='__main__':unittest.main()
