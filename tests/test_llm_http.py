"""Actual loopback HTTP provider fixture, no model or GPU resources."""
import asyncio,json,os,sys,threading,time,unittest
from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'backend'))
from fastapi import FastAPI
from fastapi.testclient import TestClient
from api import llm
from schemas.llm import Message,CompletionInput
from services.llm_service import LLMService,LLMSettings,LLMError

class LLMHTTPTests(unittest.TestCase):
    def setUp(self):
        fixture=self;self.requests=[];self.mode='ok';self.closed=threading.Event()
        class Handler(BaseHTTPRequestHandler):
            def log_message(self,*args):pass
            def do_GET(self):self.answer()
            def do_POST(self):self.answer()
            def answer(self):
                size=int(self.headers.get('Content-Length','0'));payload=self.rfile.read(size)
                fixture.requests.append((self.path,self.headers.get('Authorization'),payload))
                mode=fixture.mode
                if mode=='slow':time.sleep(1.3)
                if mode=='redirect':
                    self.send_response(302);self.send_header('Location','http://example.com');self.end_headers();return
                if mode=='auth':
                    self.send_response(401);self.end_headers();self.wfile.write(b'SECRET');return
                if mode=='large':body=b' '*262145
                elif mode=='partial':body=b'{"data":'
                elif self.command=='GET':body=json.dumps({'data':[{'id':'fixture'}]}).encode()
                else:body=json.dumps({'choices':[{'message':{'role':'assistant','content':'FAKE REPLY'},'finish_reason':'stop'}]}).encode()
                self.send_response(200);self.send_header('Content-Type','application/json');self.end_headers()
                try:self.wfile.write(body)
                except OSError:pass # Expected when a bounded client stops reading.
        self.server=ThreadingHTTPServer(('127.0.0.1',0),Handler);self.server.daemon_threads=True
        self.thread=threading.Thread(target=self.server.serve_forever,daemon=True);self.thread.start()
        self.addCleanup(self.stop)
        self.env=dict(LLM_BASE_URL=f'http://localhost:{self.server.server_port}/v1',LLM_MODEL='fixture',LLM_API_KEY='SECRET',LLM_REQUEST_TIMEOUT='1',HTTP_PROXY='http://127.0.0.1:1',ALL_PROXY='http://127.0.0.1:1')
        self.service=LLMService(LLMSettings.load(self.env))
        self.environment=patch.dict(os.environ,self.env);self.environment.start();self.addCleanup(self.environment.stop)
        llm._cached_service.cache_clear();self.addCleanup(llm._cached_service.cache_clear)
        app=FastAPI();app.include_router(llm.router)
        self.client=TestClient(app);self.addCleanup(self.client.close)
    def stop(self):
        self.server.shutdown();self.server.server_close();self.thread.join(3)
    def test_actual_http_config_models_and_fixed_probe(self):
        config=self.client.get('/api/llm/config');self.assertEqual(config.status_code,200)
        self.assertNotIn('SECRET',config.text);self.assertNotIn('http:',config.text);self.assertTrue(config.json()['configured'])
        self.assertEqual(self.requests,[],'Configuration must not trigger any upstream traffic')
        self.assertEqual(self.client.get('/api/llm/models').json(),{'models':['fixture']})
        result=self.client.post('/api/llm/check');self.assertEqual(result.status_code,200,result.text)
        self.assertEqual(result.json()['reply'],'FAKE REPLY')
        path,token,raw=self.requests[-1];self.assertEqual(token,'Bearer SECRET');self.assertEqual(path,'/v1/chat/completions')
        self.assertEqual(json.loads(raw)['messages'],[{'role':'user','content':'Reply with OK.'}])
    def test_actual_http_failures_redact_and_do_not_redirect(self):
        for mode,status,code in (('auth',503,'authentication_failed'),('redirect',502,'provider_error'),('partial',502,'invalid_response'),('large',502,'response_too_large'),('slow',504,'provider_timeout')):
            self.mode=mode;before=len(self.requests);response=self.client.get('/api/llm/models')
            self.assertEqual(response.status_code,status,response.text);self.assertEqual(response.json()['detail']['code'],code)
            self.assertNotIn('SECRET',response.text);self.assertEqual(len(self.requests),before+1)
    def test_invalid_optional_config_does_not_break_backend_health(self):
        import app
        with patch.dict(os.environ,{'LLM_BASE_URL':'http://example.com/v1'}):
            llm._cached_service.cache_clear()
            client=TestClient(app.app)
            self.addCleanup(client.close)
            self.assertEqual(client.get('/health').status_code,200)
            result=client.get('/api/llm/config');self.assertFalse(result.json()['configured'])
            self.assertEqual(result.json()['error_code'],'configuration_invalid')
            self.assertEqual(client.get('/api/llm/models').status_code,503)
    def test_message_bounds_and_localhost_pinning(self):
        self.assertIn('127.0.0.1',self.service.settings.base_url)
        self.assertEqual(LLMSettings.load({'LLM_BASE_URL':'http://[::1]:11434/v1'}).base_url,'http://[::1]:11434/v1')
        from pydantic import ValidationError
        for messages in ([],[{'role':'tool','content':'x'}],[{'role':'user','content':'x'*8001}],[{'role':'user','content':'x'}]*41,[{'role':'user','content':'x'*8000}]*3):
            with self.assertRaises(ValidationError):CompletionInput(messages=messages)

if __name__=='__main__':unittest.main()
