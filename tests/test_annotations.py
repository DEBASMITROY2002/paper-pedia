import asyncio,json,sqlite3,tempfile,unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from unittest.mock import patch
from paper_pedia.storage import annotations
from paper_pedia.server.apis import annotations as api
from paper_pedia.server.app import app
class AnnotationTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup);self.path=Path(self.tmp.name)/'annotations.sqlite3'
    def test_sparse_defaults_and_reset(self):
        self.assertEqual(annotations.lookup(self.path,['paper']),{});self.assertFalse(self.path.exists())
        self.assertEqual(annotations.update(self.path,'paper',True),{'marked':True,'comment':''})
        annotations.update(self.path,'paper',comment='Read this')
        self.assertEqual(annotations.lookup(self.path,['paper'])['paper'],{'marked':True,'comment':'Read this'})
        annotations.update(self.path,'paper',False);annotations.update(self.path,'paper',comment='')
        self.assertEqual(annotations.lookup(self.path,['paper']),{})
        with sqlite3.connect(self.path) as db:self.assertEqual(db.execute('SELECT COUNT(*) FROM annotations').fetchone()[0],0)
    def test_shared_id_and_concurrent_independent_fields(self):
        with ThreadPoolExecutor(max_workers=2) as pool:
            a=pool.submit(annotations.update,self.path,'same',True)
            b=pool.submit(annotations.update,self.path,'same',comment='note')
            a.result();b.result()
        self.assertEqual(annotations.lookup(self.path,['same','same']),{'same':{'marked':True,'comment':'note'}})
    def test_large_lookup_and_literal_content(self):
        identity="paper/@' special";comment='<script>alert(1)</script>\nUnicode: α'
        annotations.update(self.path,identity,comment=comment)
        self.assertEqual(annotations.lookup(self.path,[str(i) for i in range(1200)]+[identity])[identity]['comment'],comment)
    def call(self,path,method,payload):
        async def execute():
            messages=[]
            async def receive():return {'type':'http.request','body':json.dumps(payload).encode(),'more_body':False}
            async def send(message):messages.append(message)
            scope={'type':'http','asgi':{'version':'3.0'},'http_version':'1.1','method':method,'scheme':'http','path':path,'raw_path':path.encode(),'query_string':b'','root_path':'','headers':[(b'host',b'localhost'),(b'content-type',b'application/json')],'server':('localhost',80),'client':('127.0.0.1',1)}
            await app(scope,receive,send)
            return messages[0]['status'],json.loads(b''.join(m.get('body',b'') for m in messages))
        with patch.object(api,'ANNOTATIONS_CACHE',self.path):return asyncio.run(execute())
    def test_api_persistence_and_validation(self):
        self.assertEqual(self.call('/api/annotations/lookup','POST',{'paper_ids':['abc']}),(200,{}))
        status,note=self.call('/api/annotations','PATCH',{'paper_id':'abc','marked':True,'comment':'hello'})
        self.assertEqual((status,note),(200,{'marked':True,'comment':'hello'}))
        self.assertEqual(self.call('/api/annotations/lookup','POST',{'paper_ids':['abc']})[1]['abc'],note)
        for payload in [{'paper_id':'abc'},{'paper_id':'','marked':True},{'paper_id':'abc','marked':'yes'},{'paper_id':'abc','comment':'x'*20001}]:self.assertEqual(self.call('/api/annotations','PATCH',payload)[0],422)
    def test_failed_write_returns_error(self):
        with patch.object(annotations,'update',side_effect=sqlite3.OperationalError('disk full')):
            self.assertEqual(self.call('/api/annotations','PATCH',{'paper_id':'abc','marked':True})[0],503)
