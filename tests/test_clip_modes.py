import json, unittest
from unittest.mock import patch
from bs4 import BeautifulSoup
import numpy as np
import test_project
from paper_pedia.server import service
from paper_pedia.index import clip
from paper_pedia.storage.csv_store import save_papers_csv
class Encoder:
    device='cpu'
    def encode(self,texts):
        rows=np.array([[1+text.lower().count('graph'),1+text.lower().count('image')] for text in texts],dtype=np.float32)
        return rows/np.linalg.norm(rows,axis=1,keepdims=True)
    def scores(self,matrix,query):return matrix@query
class ClipTests(unittest.TestCase):
    call=test_project.ProjectTests.call
    def setUp(self):
        test_project.ProjectTests.setUp(self)
        for name,folder in [('CLIP_INDICES_DIR','clip_indices'),('CLIP_MODEL_DIR','models/clip'),('SPLADE_INDICES_DIR','splade_indices'),('INDICES_DIR','indices')]:
            p=patch.object(service,name,self.venues.parent/folder);p.start();self.addCleanup(p.stop)
        self.encoder=Encoder();p=patch.object(clip,'get_encoder',return_value=self.encoder);p.start();self.addCleanup(p.stop)
        self.path=service.csv_path('AAAI',2026);save_papers_csv(self.papers,self.path)
    def test_four_modes_and_independent_readiness(self):
        service.build_collection_clip('AAAI',2026)
        for mode,disabled in [('dense',False),('splade',True),('sparse',True),('subset',True)]:
            status,html=self.call('/search',query='venue=AAAI&year=2026&mode='+mode)
            soup=BeautifulSoup(html,'html.parser');self.assertEqual(status,200)
            self.assertEqual({i['value'] for i in soup.select('input[name=mode]')},{'dense','splade','sparse','subset'})
            self.assertEqual(soup.select_one('[data-search-submit]').has_attr('disabled'),disabled)
        self.assertIn('scheme=dense',html)
    def test_api_build_and_search(self):
        self.assertEqual(self.call('/api/venues/clip-index','POST','venue=AAAI&year=2026')[0],200)
        status,body=self.call('/api/venues/search',query='venue=AAAI&year=2026&mode=dense&q=graph&k=1')
        self.assertEqual(status,200);result=json.loads(body);self.assertEqual(result['count'],1)
        self.assertLessEqual(result['papers'][0]['score'],1)
        self.assertTrue(service.collection_clip_status('AAAI',2026)['indexed'])
        self.assertFalse(service.collection_splade_status('AAAI',2026)['indexed'])
    def test_missing_stale_reindex_and_failed_replacement(self):
        with self.assertRaises(service.IndexUnavailable):service.search_collection('AAAI',2026,'','graph',1,'dense')
        service.build_collection_clip('AAAI',2026);path=clip.index_path(self.path,service.CLIP_INDICES_DIR);before=path.read_bytes()
        with patch.object(self.encoder,'encode',side_effect=RuntimeError('failed')):
            with self.assertRaises(service.IndexUnavailable):service.build_collection_clip('AAAI',2026,force=True)
        self.assertEqual(before,path.read_bytes())
        save_papers_csv(self.papers[:1],self.path)
        self.assertEqual(service.collection_clip_status('AAAI',2026)['state'],'stale')
        service.build_collection_clip('AAAI',2026,force=True)
        self.assertEqual(service.collection_clip_status('AAAI',2026)['count'],1)
    def test_buttons_on_home_and_papers(self):
        for route in ['/', '/papers']:
            status,html=self.call(route,query='venue=AAAI&year=2026' if route=='/papers' else '')
            self.assertEqual(status,200);self.assertIn('Index CLIP',html);self.assertIn('Index SPLADE',html)
