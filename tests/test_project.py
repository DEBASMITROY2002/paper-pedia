import asyncio, json, tempfile, unittest
from pathlib import Path
from unittest.mock import patch
from paper_pedia.scraper.papers_cool import PapersCoolScraper, ScrapeError
from paper_pedia.storage.csv_store import save_papers_csv, load_papers_csv
from paper_pedia.server import service
from paper_pedia.server.app import app
FIXTURE = (Path(__file__).parent / 'fixtures/papers.html').read_text()
CATALOG = {'updated_at': '2026-09-30T00:00:00+00:00', 'venues': {'AAAI': {'2026': ['Application Domains']}, 'ICLR': {'2024': ['Spotlight', 'Notable-top-5%']}}}
async def request(path='/', method='GET', query='', wait_jobs=True):
    messages = []
    async def receive(): return {'type': 'http.request', 'body': b'', 'more_body': False}
    async def send(message): messages.append(message)
    scope = {'type': 'http', 'asgi': {'version': '3.0'}, 'http_version': '1.1', 'method': method, 'scheme': 'http', 'path': path, 'raw_path': path.encode(), 'query_string': query.encode(), 'root_path': '', 'headers': [(b'host', b'localhost')], 'server': ('localhost', 80), 'client': ('127.0.0.1', 10000)}
    await app(scope, receive, send)
    status, body = messages[0]['status'], b''.join(m.get('body', b'') for m in messages).decode()
    if status == 202 and wait_jobs:
        from paper_pedia.server.jobs import manager
        location = dict(messages[0].get('headers', [])).get(b'location', b'').decode()
        identity = location.rsplit('/',1)[-1]
        for _ in range(1000):
            if manager.get(identity)['state'] not in {'queued','running'}: break
            await asyncio.sleep(.01)
        response = manager.result(identity)
        return response.status_code, response.body.decode()
    return status, body
class ProjectTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        root = Path(self.tmp.name)
        self.catalog, self.venues = root/'catalog.json', root/'venues'
        self.catalog.write_text(json.dumps(CATALOG))
        self.venues.mkdir()
        for name, value in [('CATALOG_CACHE', self.catalog), ('VENUES_DIR', self.venues)]:
            p = patch.object(service, name, value); p.start(); self.addCleanup(p.stop)
        self.papers, _ = PapersCoolScraper()._parse_page(FIXTURE, 'AAAI.2026', 'Application Domains')
    def call(self, *args, **kwargs): return asyncio.run(request(*args, **kwargs))
    def test_real_markup_and_csv_round_trip(self):
        self.assertEqual(len(self.papers), 2)
        self.assertTrue(self.papers[0].abstract and self.papers[0].authors)
        self.assertTrue(self.papers[0].pdf_url.startswith('https://'))
        path = self.venues/'roundtrip.csv'; save_papers_csv(self.papers, path)
        self.assertEqual(load_papers_csv(path)[0]['authors'], self.papers[0].authors)
    def test_catalog_url_decoding(self):
        html = '<a href="/venue/ICLR.2024?group=Notable-top-5%25">g</a><a href="https://evil.invalid/venue/BAD.2026">bad</a>'
        self.assertEqual(PapersCoolScraper._parse_catalog(html), {'ICLR': {'2024': ['Notable-top-5%']}})
    def test_pagination(self):
        scraper = PapersCoolScraper(page_size=1, delay=0)
        with patch.object(scraper, '_fetch_page', return_value='html') as fetch, patch.object(scraper, '_parse_page', side_effect=[([self.papers[0]], 2), ([self.papers[1]], 2)]):
            self.assertEqual(len(scraper.scrape_venue('AAAI.2026')), 2)
        self.assertEqual([call.args[2] for call in fetch.call_args_list], [0, 1])
    def test_incomplete_and_repeated_pages(self):
        for second in ([], [self.papers[0]]):
            scraper = PapersCoolScraper(page_size=1, delay=0)
            with patch.object(scraper, '_fetch_page', return_value='html'), patch.object(scraper, '_parse_page', side_effect=[([self.papers[0]], 2), (second, 2)]):
                with self.assertRaises(ScrapeError): scraper.scrape_venue('AAAI.2026')
    def test_bad_source_not_cached_as_empty(self):
        with patch.object(PapersCoolScraper, '_fetch_page', return_value='<html>Challenge page</html>'):
            with self.assertRaises(ScrapeError): PapersCoolScraper().scrape_venue('AAAI.2026')
    def test_cache_reuse_and_refresh(self):
        with patch.object(service.scraper, 'scrape_venue', return_value=self.papers) as fetch:
            data, path = service.get_papers('AAAI', 2026, 'Application Domains')
            service.get_papers('AAAI', 2026, 'Application Domains')
            self.assertEqual(fetch.call_count, 1)
            service.get_papers('AAAI', 2026, 'Application Domains', True)
            self.assertEqual(fetch.call_count, 2)
            self.assertEqual(path.name, 'AAAI.2026__Application_Domains.csv')
    def test_empty_cache(self):
        with patch.object(service.scraper, 'scrape_venue', return_value=[]) as fetch:
            self.assertEqual(service.get_papers('AAAI', 2026)[0], [])
            service.get_papers('AAAI', 2026)
            self.assertEqual(fetch.call_count, 1)
    def test_failed_refresh_preserves_papers(self):
        path = service.csv_path('AAAI', 2026, 'Application Domains'); save_papers_csv(self.papers, path)
        before = path.read_bytes()
        with patch.object(service.scraper, 'scrape_venue', side_effect=ScrapeError('Source unavailable')):
            status, body = self.call('/papers/refresh', 'POST', 'venue=AAAI&year=2026&group=Application+Domains')
        self.assertEqual(status, 502)
        self.assertIn('Showing the previous cached papers', body)
        self.assertEqual(path.read_bytes(), before)
    def test_failed_catalog_refresh_preserves_catalog(self):
        before = self.catalog.read_bytes()
        with patch.object(service.scraper, 'scrape_catalog', side_effect=ScrapeError('Unavailable')):
            status, body = self.call('/cache/refresh', 'POST')
        self.assertEqual(status, 502); self.assertIn('AAAI', body)
        self.assertEqual(self.catalog.read_bytes(), before)
    def test_server_rendered_home(self):
        with patch.object(service.scraper, 'scrape_catalog', side_effect=AssertionError('Should use cache')):
            status, body = self.call()
        self.assertEqual(status, 200)
        for text in ['AAAI', '2026', 'Application Domains', 'ICLR', '2024', 'Spotlight', 'Notable-top-5%', 'Not cached']:
            self.assertIn(text, body)
        self.assertIn('group=Notable-top-5%25', body); self.assertNotIn('<script>', body)
    def test_catalog_refresh(self):
        with patch.object(service.scraper, 'scrape_catalog', return_value={'NEW': {'2026': ['Oral']}}):
            self.assertEqual(self.call('/cache/refresh', 'POST')[0], 303)
        self.assertIn('NEW', json.loads(self.catalog.read_text())['venues'])
    def test_api_and_download(self):
        query='venue=AAAI&year=2026&group=Application+Domains'
        with patch.object(service.scraper, 'scrape_venue', return_value=self.papers):
            status, body = self.call('/api/venues/papers', query=query)
        self.assertEqual(status, 200); self.assertEqual(json.loads(body)['count'], 2)
        status, body = self.call('/api/venues/csv', query=query)
        self.assertEqual(status, 200); self.assertIn('paper_id,index,venue', body)
    def test_invalid_selection(self):
        self.assertEqual(self.call('/papers', query='venue=AAAI&year=2026&group=wrong')[0], 404)
        self.assertEqual(self.call('/api/venues/papers', query='venue=../bad&year=2026')[0], 404)
        self.assertEqual(self.call('/papers', query='venue=AAAI')[0], 422)
        self.assertEqual(self.call('/api/venues/csv', query='venue=AAAI&year=2026')[0], 404)
    def test_cold_start_offline(self):
        self.catalog.unlink()
        with patch.object(service.scraper, 'scrape_catalog', return_value=CATALOG['venues']):
            self.assertEqual(self.call()[0], 200)
        self.catalog.unlink()
        with patch.object(service.scraper, 'scrape_catalog', side_effect=ScrapeError('Offline')):
            self.assertEqual(self.call()[0], 503)
    def test_escaped_content_and_safe_links(self):
        self.papers[0].title='<script>alert(1)</script>'; self.papers[0].papers_cool_url='javascript:alert(1)'
        save_papers_csv(self.papers, service.csv_path('AAAI', 2026))
        status, body = self.call('/papers', query='venue=AAAI&year=2026')
        self.assertEqual(status, 200); self.assertIn('&lt;script&gt;', body); self.assertNotIn('href="javascript:', body)
    def test_distinct_filenames(self):
        names=[service.csv_path('AAAI', 2026, g).name for g in ['', 'All', 'A B', 'A_B', 'A/B', 'A%B']]
        self.assertEqual(len(set(names)), len(names))
if __name__ == '__main__': unittest.main()
