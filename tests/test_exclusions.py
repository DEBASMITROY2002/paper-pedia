import json, unittest
from dataclasses import replace
from urllib.parse import urlencode
from unittest.mock import patch
import test_project
from paper_pedia.server import service
from paper_pedia.index import clip, splade
from paper_pedia.storage.csv_store import save_papers_csv
from test_clip_modes import Encoder
from test_splade_modes import FakeEncoder
class ExclusionTests(unittest.TestCase):
    call = test_project.ProjectTests.call
    def setUp(self):
        test_project.ProjectTests.setUp(self)
        for key, folder in [('INDICES_DIR','indices'),('CLIP_INDICES_DIR','clip'),('SPLADE_INDICES_DIR','splade'),('CLIP_MODEL_DIR','models/clip'),('SPLADE_MODEL_DIR','models/splade')]:
            p=patch.object(service,key,self.venues.parent/folder);p.start();self.addCleanup(p.stop)
        for module,encoder in [(clip,Encoder()),(splade,FakeEncoder())]:
            p=patch.object(module,'get_encoder',return_value=encoder);p.start();self.addCleanup(p.stop)
        self.rows=[replace(self.papers[0],paper_id=str(i),title=title,abstract='') for i,title in enumerate(['graph','graph image','image'])]
        save_papers_csv(self.rows,service.csv_path('AAAI',2026))
        for fn in [service.build_collection_index,service.build_collection_clip,service.build_collection_splade]:fn('AAAI',2026)
    def search(self,mode,q='graph',exclude='image'):
        return service.search_collection('AAAI',2026,'',q,10,mode,exclude)
    def test_exact_signed_scoring_all_modes(self):
        # Equal graph/image document frequencies make the TF-IDF basis symmetric.
        for mode in ['sparse','subset']:
            rows=self.search(mode);self.assertEqual([r['paper_id'] for r in rows],['0']);self.assertAlmostEqual(rows[0]['score'],1)
        rows=self.search('splade');self.assertEqual([r['paper_id'] for r in rows],['0']);self.assertAlmostEqual(rows[0]['score'],4)
        rows=self.search('dense');encoder=Encoder();delta=encoder.encode(['graph'])[0]-encoder.encode(['image'])[0]
        for row in rows:
            expected=float(encoder.encode([self.rows[int(row['paper_id'])].title+'. '])[0]@delta)
            self.assertAlmostEqual(row['score'],expected,places=6)
        self.assertEqual(rows[0]['paper_id'],'0');self.assertLess(rows[-1]['score'],0)
    def test_cancellation_and_blank_exclusion(self):
        for mode in ['sparse','subset','dense','splade']:
            self.assertEqual(self.search(mode,exclude='graph'),[])
            self.assertEqual(self.search(mode,exclude='  '),service.search_collection('AAAI',2026,'','graph',10,mode))
    def test_jaccard_penalty_uses_excluded_oov_terms_in_union(self):
        rows=self.search('subset',q='graph image',exclude='image unseen')
        scores={r['paper_id']:r['score'] for r in rows}
        self.assertAlmostEqual(scores['1'],1-1/3);self.assertAlmostEqual(scores['0'],.5)
    def test_global_and_api_propagation(self):
        save_papers_csv(self.rows,service.csv_path('ICLR',2024,'Spotlight'))
        for fn in [service.build_collection_index,service.build_collection_clip,service.build_collection_splade]:fn('ICLR',2024,'Spotlight')
        for mode in ['sparse','subset','dense','splade']:
            result=service.search_global('graph',10,mode,'image')
            self.assertEqual(result['collections_searched'],2);self.assertEqual(result['papers'][0]['paper_id'],'0')
            for route,params in [('/api/venues/search',{'venue':'AAAI','year':2026}),('/api/venues/search-all',{})]:
                status,body=self.call(route,query=urlencode({**params,'q':'graph','exclude':'graph','mode':mode}))
                self.assertEqual(status,200);self.assertEqual(json.loads(body)['papers'],[]);self.assertEqual(json.loads(body)['exclude'],'graph')
    def test_form_escaping_and_validation(self):
        from bs4 import BeautifulSoup
        value='<script>alert(1)</script>'
        for scope in ['venue','global']:
            status,html=self.call('/search',query=urlencode({'venue':'AAAI','year':2026,'scope':scope,'exclude':value}))
            self.assertEqual(status,200);self.assertNotIn(value,html)
            self.assertEqual(BeautifulSoup(html,'html.parser').select_one('input[name=exclude]')['value'],value)
        status,_=self.call('/api/venues/search-all',query=urlencode({'q':'graph','exclude':'x'*1001}))
        self.assertEqual(status,422)
