import gc, unittest, weakref
from dataclasses import replace
from unittest.mock import patch
from bs4 import BeautifulSoup
import test_project
from paper_pedia.server import service
from paper_pedia.index import clip, splade_encoder, clip_encoder
from paper_pedia.index.memory import session
from paper_pedia.storage.csv_store import save_papers_csv
class GlobalTests(unittest.TestCase):
    call=test_project.ProjectTests.call
    def setUp(self):
        test_project.ProjectTests.setUp(self)
        for key,folder in [('INDICES_DIR','indices'),('CLIP_INDICES_DIR','clip_indices'),('SPLADE_INDICES_DIR','splade_indices')]:
            p=patch.object(service,key,self.venues.parent/folder);p.start();self.addCleanup(p.stop)
        self.one=service.csv_path('AAAI',2026);self.two=service.csv_path('ICLR',2024,'Spotlight')
        self.rows=[replace(self.papers[0],paper_id='shared',title='graph networks',abstract='graph'),replace(self.papers[1],paper_id='unique',title='graph methods',abstract='graph graph')]
        save_papers_csv(self.rows,self.one);save_papers_csv(self.rows[:1],self.two)
        service.build_collection_index('AAAI',2026);service.build_collection_index('ICLR',2024,'Spotlight')
    def test_global_deduplicates_and_uses_fresh_matching_indexes(self):
        result=service.search_global('graph',10,'sparse')
        self.assertEqual(result['collections_searched'],2);self.assertEqual(len(result['papers']),2)
        self.assertEqual({p['paper_id'] for p in result['papers']},{'shared','unique'})
        save_papers_csv(self.rows,self.two)
        self.assertEqual(service.search_global('graph',10,'subset')['collections_searched'],1)
        with self.assertRaises(service.IndexUnavailable):service.search_global('graph',10,'splade')
    def test_global_bounded_top_k_and_api(self):
        self.assertEqual(len(service.search_global('graph',1)['papers']),1)
        status,body=self.call('/api/venues/search-all',query='q=graph&mode=subset&k=1')
        self.assertEqual(status,200);self.assertIn('collections_searched',body)
    def test_global_page_readiness(self):
        for mode,disabled in [('sparse',False),('subset',False),('dense',True),('splade',True)]:
            status,html=self.call('/search',query='scope=global&mode='+mode)
            soup=BeautifulSoup(html,'html.parser');self.assertEqual(status,200)
            self.assertEqual(soup.select_one('[data-search-submit]').has_attr('disabled'),disabled)
            self.assertIsNone(soup.select_one('select[name=selection]'))
        status,html=self.call('/search',query='scope=global&mode=sparse&q=graph')
        self.assertEqual(status,200);self.assertIn('2 indexed collections',html)
    def test_failure_skipped_without_discarding_other_results(self):
        original=service.search_index.search
        def query(path,*args):
            if path==self.two:raise service.search_index.IndexFailure('broken')
            return original(path,*args)
        with patch.object(service.search_index,'search',side_effect=query):
            result=service.search_global('graph',5)
        self.assertEqual(result['collections_searched'],1);self.assertEqual(result['skipped'],[self.two.name])
class MemoryTests(unittest.TestCase):
    def test_models_released_at_outer_boundary_and_on_failure(self):
        class Encoder:pass
        for module,constructor in [(clip_encoder,'ClipEncoder'),(splade_encoder,'SpladeEncoder')]:
            module._cached_encoder.cache_clear()
            with patch.object(module,constructor,side_effect=lambda *_:Encoder()):
                with self.assertRaises(RuntimeError):
                    with session():
                        with session():reference=weakref.ref(module.get_encoder('test'))
                        self.assertIsNotNone(reference());raise RuntimeError('search failure')
                gc.collect();self.assertIsNone(reference());self.assertEqual(module._cached_encoder.cache_info().currsize,0)
    def test_clip_streams_embeddings_in_bounded_batches(self):
        import tempfile,numpy as np
        from pathlib import Path
        from test_clip_modes import Encoder
        fixture=test_project.ProjectTests();fixture.setUp()
        self.addCleanup(fixture.doCleanups)
        rows=[replace(fixture.papers[0],paper_id=str(i)) for i in range(600)]
        path=fixture.venues/'AAAI.2026__All.csv';save_papers_csv(rows,path)
        encoder=Encoder()
        with patch.object(clip,'get_encoder',return_value=encoder),patch.object(encoder,'scores',wraps=encoder.scores) as score:
            clip.build_index(path,fixture.venues.parent/'clip',fixture.venues.parent/'models')
            results=clip.search(path,fixture.venues.parent/'clip',fixture.venues.parent/'models','graph',3)
        self.assertEqual([call.args[0].shape[0] for call in score.call_args_list],[256,256,88])
        self.assertEqual(len(results),3);self.assertFalse(hasattr(clip,'_load'))
