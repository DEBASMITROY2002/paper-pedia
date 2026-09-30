import json, math, sqlite3, unittest
from dataclasses import replace
from unittest.mock import patch
from urllib.parse import urlencode
from bs4 import BeautifulSoup
import test_project
from paper_pedia.index import tfidf
from paper_pedia.index.preprocess import normalize
from paper_pedia.server import service
from paper_pedia.storage.csv_store import save_papers_csv
class IndexTests(unittest.TestCase):
    call = test_project.ProjectTests.call
    def setUp(self):
        test_project.ProjectTests.setUp(self)
        self.indices = self.venues.parent/'indices'
        p=patch.object(service,'INDICES_DIR',self.indices); p.start(); self.addCleanup(p.stop)
        self.path=service.csv_path('AAAI',2026)
        self.rows=[replace(self.papers[0],paper_id='graph',title='Graph neural networks',abstract='Graph learning for graph classification'),replace(self.papers[0],paper_id='vision',title='Visual image reconstruction',abstract='Rendering scenes and cameras'),replace(self.papers[0],paper_id='robot',title='Robot motion planning',abstract='Autonomous navigation and control')]
        save_papers_csv(self.rows,self.path)
    def test_normalization_and_stemming(self):
        self.assertEqual(normalize('<p>The CAFÉ &amp; Deep-Learning [12]</p> https://example.com'),'cafe deep learning')
        self.assertEqual(tfidf._query_counts('LEARNING learned learns'),{'learn':3})
        self.assertNotIn('alert',normalize('<script>alert(1)</script>Research'))
    def test_build_persists_and_status(self):
        info=service.build_collection_index('AAAI',2026)
        self.assertEqual(info['state'],'indexed'); self.assertEqual(info['count'],3)
        self.assertEqual(tfidf.index_path(self.path,self.indices).name,'AAAI.2026__All.tfidf.sqlite3')
        self.assertEqual(tfidf.search(self.path,self.indices,'graph classification',1)[0]['paper_id'],'graph')
        with sqlite3.connect(tfidf.index_path(self.path,self.indices)) as db:
            for norm, in db.execute('SELECT SUM(weight*weight) FROM postings GROUP BY doc'): self.assertAlmostEqual(norm,1)
    def test_cosine_scoring_matches_formula(self):
        save_papers_csv([replace(self.rows[0],title='apple banana',abstract=''),replace(self.rows[1],title='apple apple banana cherry',abstract='')],self.path)
        service.build_collection_index('AAAI',2026)
        results=service.search_collection('AAAI',2026,'','apple',2)
        expected=(1+math.log(2))/math.sqrt((1+math.log(2))**2+1+(1+math.log(3/2))**2)
        scores={r['paper_id']:r['score'] for r in results}
        self.assertAlmostEqual(scores['graph'],1/math.sqrt(2))
        self.assertAlmostEqual(scores['vision'],expected)
        self.assertGreaterEqual(results[0]['score'],results[1]['score'])
    def test_isolation_and_top_k(self):
        save_papers_csv([replace(self.rows[1],paper_id='other',title='Graph networks',abstract='')],service.csv_path('ICLR',2024,'Spotlight'))
        service.build_collection_index('AAAI',2026); service.build_collection_index('ICLR',2024,'Spotlight')
        results=service.search_collection('AAAI',2026,'','graph networks image',1)
        self.assertEqual(len(results),1); self.assertNotEqual(results[0]['paper_id'],'other')
        self.assertEqual(service.search_collection('ICLR',2024,'Spotlight','graph',10)[0]['paper_id'],'other')
    def test_stale_index_blocks_search_then_rebuilds(self):
        service.build_collection_index('AAAI',2026)
        save_papers_csv([replace(self.rows[0],title='Quantum physics',abstract='quantum optics')],self.path)
        self.assertEqual(service.collection_index_status('AAAI',2026)['state'],'stale')
        with self.assertRaises(service.IndexUnavailable): service.search_collection('AAAI',2026,'','graph')
        service.build_collection_index('AAAI',2026,force=True)
        self.assertEqual(len(service.search_collection('AAAI',2026,'','quantum')),1)
    def test_missing_empty_and_no_matches(self):
        self.assertEqual(service.collection_index_status('AAAI',2026)['state'],'missing')
        with self.assertRaises(service.IndexUnavailable): service.search_collection('AAAI',2026,'','graph')
        save_papers_csv([],self.path); service.build_collection_index('AAAI',2026)
        self.assertEqual(service.search_collection('AAAI',2026,'','graph'),[])
        self.assertEqual(service.search_collection('AAAI',2026,'','the and of'),[])
    def test_failed_reindex_preserves_previous(self):
        service.build_collection_index('AAAI',2026)
        path=tfidf.index_path(self.path,self.indices); before=path.read_bytes()
        with patch.object(tfidf,'normalize',side_effect=ValueError('bad preprocessing')):
            with self.assertRaises(service.IndexUnavailable): service.build_collection_index('AAAI',2026,force=True)
        self.assertEqual(path.read_bytes(),before)
        self.assertFalse(list(self.indices.glob('*.tmp')))
    def test_partial_csv_rejected(self):
        partial=self.path.with_suffix('.partial.csv'); save_papers_csv(self.rows,partial)
        with self.assertRaises(tfidf.IndexFailure): tfidf.build_index(partial,self.indices)
    def test_corrupt_index_rebuild(self):
        self.indices.mkdir(); tfidf.index_path(self.path,self.indices).write_bytes(b'invalid')
        self.assertEqual(service.collection_index_status('AAAI',2026)['state'],'invalid')
        self.assertTrue(service.build_collection_index('AAAI',2026)['indexed'])
    def test_home_actions_and_search_form(self):
        status,html=self.call(); self.assertEqual(status,200); self.assertIn('Not indexed',html)
        self.assertIn('/indices/build?',html)
        status,html=self.call('/indices/build','POST','venue=AAAI&year=2026'); self.assertEqual(status,303)
        status,html=self.call(); self.assertIn('Indexed',html); self.assertIn('Reindex',html)
        status,html=self.call('/search',query='venue=AAAI&year=2026&q=graph&k=1')
        self.assertEqual(status,200)
        soup=BeautifulSoup(html,'html.parser'); self.assertEqual(len(soup.select('.paper-card')),1)
        self.assertIn('Graph neural networks',html); self.assertNotIn('id="render-result"',html)
        self.assertIsNotNone(soup.select_one('input[type="search"]'))
    def test_api_validation_and_search(self):
        self.assertEqual(self.call('/api/venues/search',query='venue=AAAI&year=2026&q=graph')[0],409)
        self.assertEqual(self.call('/api/venues/index','POST','venue=AAAI&year=2026')[0],200)
        status,body=self.call('/api/venues/search',query='venue=AAAI&year=2026&q=graph&k=1')
        self.assertEqual(status,200); self.assertEqual(json.loads(body)['papers'][0]['paper_id'],'graph')
        self.assertEqual(self.call('/api/venues/search',query='venue=AAAI&year=2026&q=graph&k=0')[0],422)
        self.assertEqual(self.call('/api/venues/search',query='venue=AAAI&year=2026&q=graph&k=101')[0],422)
        self.assertEqual(self.call('/api/venues/search',query='venue=AAAI&year=2026&q=%20')[0],422)
        self.assertEqual(self.call('/api/venues/index','POST','venue=AAAI&year=2026&group=Invalid')[0],404)
    def test_select_collection_and_preserve_query(self):
        service.build_collection_index('AAAI',2026)
        query=urlencode({'selection':service.selection_query('AAAI',2026),'q':'graph','k':2})
        status,html=self.call('/search',query=query); self.assertEqual(status,200); self.assertIn('Graph neural networks',html)
        self.assertEqual(self.call('/search',query='selection=malformed&q=graph')[0],422)
