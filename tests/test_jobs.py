import asyncio, json, logging, threading, time, unittest
from unittest.mock import patch
from fastapi import HTTPException
from fastapi.responses import JSONResponse
import test_project
from paper_pedia.server import jobs, service
class JobTests(unittest.TestCase):
    def setUp(self):
        self.manager=jobs.JobManager(workers=2,capacity=3)
        self.release=threading.Event()
        self.addCleanup(self.manager.shutdown);self.addCleanup(self.release.set)
    def wait(self,identity):
        for _ in range(200):
            state=self.manager.get(identity)
            if state['state'] not in {'queued','running'}:return state
            time.sleep(.01)
        self.fail('Job did not finish')
    def test_deduplication_queue_capacity_and_results(self):
        def block():self.release.wait(3);return JSONResponse({'count':7})
        first=self.manager.submit('same','Render',block)
        self.assertEqual(self.manager.submit('same','Render',block)['id'],first['id'])
        self.assertEqual(self.manager.result(first['id']).status_code,202)
        self.manager.submit('two','Render',block);self.manager.submit('three','Render',block)
        with self.assertRaises(HTTPException) as error:self.manager.submit('four','Render',block)
        self.assertEqual(error.exception.status_code,429)
        self.release.set();state=self.wait(first['id'])
        self.assertEqual(state['state'],'completed');self.assertIn('7 papers',state['message'])
        self.assertEqual(json.loads(self.manager.result(first['id']).body),{'count':7})
    def test_failure_and_progress(self):
        def fail():
            logging.getLogger('paper_pedia.index.test').info('SPLADE index progress papers=128 total=999')
            raise HTTPException(409,'Reindex required')
        job=self.manager.submit('failure','Index',fail);state=self.wait(job['id'])
        self.assertEqual(state['state'],'failed');self.assertEqual(state['count'],128)
        self.assertEqual(self.manager.result(job['id']).status_code,409)
    def test_other_worker_can_finish_while_one_is_blocked(self):
        def block():self.release.wait(3);return JSONResponse({})
        first=self.manager.submit('slow','Render',block)
        second=self.manager.submit('fast','Index',lambda:JSONResponse({}))
        self.assertEqual(self.wait(second['id'])['state'],'completed')
        self.assertIn(self.manager.get(first['id'])['state'],{'queued','running'})
    def test_unknown_job(self):
        with self.assertRaises(HTTPException) as error:self.manager.get('missing')
        self.assertEqual(error.exception.status_code,404)
class BackgroundRouteTests(unittest.TestCase):
    def setUp(self):
        test_project.ProjectTests.setUp(self)
        self.manager=jobs.JobManager(workers=2)
        self.release=threading.Event()
        p=patch.object(jobs,'manager',self.manager);p.start();self.addCleanup(p.stop)
        self.addCleanup(self.manager.shutdown);self.addCleanup(self.release.set)
    def test_immediate_response_and_browsing_during_scrape(self):
        entered=threading.Event()
        def scrape(*args,**kwargs):entered.set();self.release.wait(5);return self.papers
        with patch.object(service.scraper,'scrape_venue',side_effect=scrape):
            async def check():
                status,body=await test_project.request('/api/venues/papers',query='venue=AAAI&year=2026',wait_jobs=False)
                self.assertEqual(status,202);identity=json.loads(body)['id']
                self.assertTrue(await asyncio.to_thread(entered.wait,2))
                status,_=await asyncio.wait_for(test_project.request('/'),2)
                self.assertEqual(status,200)
                status,body=await test_project.request('/api/jobs/'+identity,wait_jobs=False)
                self.assertEqual(status,200);self.assertEqual(json.loads(body)['state'],'running')
                self.release.set()
                for _ in range(200):
                    if self.manager.get(identity)['state']=='completed':break
                    await asyncio.sleep(.01)
                self.assertEqual(self.manager.get(identity)['state'],'completed')
                status,body=await test_project.request('/api/jobs/'+identity+'/result',wait_jobs=False)
                self.assertEqual(status,200);self.assertEqual(json.loads(body)['count'],2)
            asyncio.run(check())
    def test_catalog_refresh_does_not_block_cached_home(self):
        entered=threading.Event()
        def refresh():entered.set();self.release.wait(5);return test_project.CATALOG['venues']
        with patch.object(service.scraper,'scrape_catalog',side_effect=refresh):
            async def check():
                status,body=await test_project.request('/cache/refresh','POST',wait_jobs=False)
                self.assertEqual(status,202);self.assertIn('Processing in background',body)
                self.assertTrue(await asyncio.to_thread(entered.wait,2))
                status,_=await asyncio.wait_for(test_project.request('/'),2);self.assertEqual(status,200)
                self.release.set()
                while any(j['state'] in {'queued','running'} for j in self.manager.jobs.values()):await asyncio.sleep(.01)
            asyncio.run(check())
    def test_invalid_input_is_failed_job_with_original_status(self):
        async def check():
            status,body=await test_project.request('/api/venues/search',query='venue=AAAI&year=no&q=test',wait_jobs=False)
            self.assertEqual(status,202);identity=json.loads(body)['id']
            for _ in range(200):
                if self.manager.get(identity)['state']=='failed':break
                await asyncio.sleep(.01)
            self.assertEqual(self.manager.result(identity).status_code,422)
        asyncio.run(check())
