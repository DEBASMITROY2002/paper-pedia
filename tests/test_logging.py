import asyncio, io, logging, unittest
from paper_pedia.logging_config import configure_logging, request_id, RequestContext
from paper_pedia.server.request_logging import RequestLoggingMiddleware
class LoggingTests(unittest.TestCase):
    def test_configuration_is_idempotent(self):
        configure_logging()
        logger = logging.getLogger('paper_pedia')
        before = list(logger.handlers)
        configure_logging()
        self.assertEqual(logger.handlers, before)
        self.assertTrue(any(isinstance(h, logging.handlers.RotatingFileHandler) for h in before))
    def test_concurrent_request_context_and_headers(self):
        output = io.StringIO()
        handler = logging.StreamHandler(output)
        handler.addFilter(RequestContext())
        handler.setFormatter(logging.Formatter('%(request_id)s %(message)s'))
        logger = logging.getLogger('paper_pedia')
        logger.addHandler(handler)
        self.addCleanup(logger.removeHandler, handler)
        async def endpoint(scope, receive, send):
            await asyncio.to_thread(logger.info, 'Worker %s', scope['path'])
            await send({'type':'http.response.start','status':200,'headers':[]})
            await send({'type':'http.response.body','body':b'ok'})
        async def call(path):
            messages=[]
            async def send(message): messages.append(message)
            await RequestLoggingMiddleware(endpoint)({'type':'http','method':'GET','path':path,'query_string':b'token=secret&venue=ICLR'}, None, send)
            self.assertEqual(request_id.get(), '-')
            return dict(messages[0]['headers'])[b'x-request-id'].decode()
        async def run(): return await asyncio.gather(call('/a'),call('/b'))
        ids=asyncio.run(run())
        self.assertNotEqual(ids[0], ids[1])
        for identifier,path in zip(ids,['/a','/b']):
            self.assertIn(identifier+' Worker '+path, output.getvalue())
        self.assertNotIn('secret',output.getvalue())
        self.assertIn('duration_ms=',output.getvalue())
    def test_unhandled_error_logged_and_context_reset(self):
        async def endpoint(scope, receive, send): raise RuntimeError('Failure example')
        with self.assertLogs('paper_pedia.server.request_logging', level='ERROR') as logs:
            with self.assertRaises(RuntimeError):
                asyncio.run(RequestLoggingMiddleware(endpoint)({'type':'http','method':'GET','path':'/failure'},None,None))
        self.assertTrue(any(r.exc_info for r in logs.records))
        self.assertIn('status=500',' '.join(logs.output))
        self.assertEqual(request_id.get(), '-')
