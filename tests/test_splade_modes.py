import math, os, unittest
from dataclasses import replace
from types import SimpleNamespace
from unittest.mock import patch
import numpy as np
from bs4 import BeautifulSoup
import test_project
from paper_pedia.server import service
from paper_pedia.index import splade, jaccard
from paper_pedia.index.tfidf import IndexFailure
from paper_pedia.index.splade_encoder import select_device, SpladeEncoder
from paper_pedia.storage.csv_store import save_papers_csv
class FakeEncoder:
    device='cpu'; dimension=30522
    def encode(self,texts):
        return [{i:float(text.lower().count(word)*2) for i,word in enumerate(['graph','image','robot']) if word in text.lower()} for text in texts]
class SpladeModeTests(unittest.TestCase):
    call=test_project.ProjectTests.call
    def setUp(self):
        test_project.ProjectTests.setUp(self)
        self.indices=self.venues.parent/'indices'; self.splade=self.venues.parent/'splade_indices'
        for name,value in [('INDICES_DIR',self.indices),('SPLADE_INDICES_DIR',self.splade),('SPLADE_MODEL_DIR',self.venues.parent/'models')]:
            p=patch.object(service,name,value);p.start();self.addCleanup(p.stop)
        self.encoder=FakeEncoder()
        p=patch.object(splade,'get_encoder',return_value=self.encoder);self.mock_encoder=p.start();self.addCleanup(p.stop)
        self.path=service.csv_path('AAAI',2026)
        self.rows=[replace(self.papers[0],paper_id='graphs',title='graph graph neural network',abstract='graph learning'),replace(self.papers[1],paper_id='images',title='image image image reconstruction',abstract='image generation')]
        save_papers_csv(self.rows,self.path)
    def test_device_selection(self):
        for mps,cuda,expected in [(True,True,'mps'),(False,True,'cuda'),(False,False,'cpu')]:
            torch=SimpleNamespace(backends=SimpleNamespace(mps=SimpleNamespace(is_available=lambda:mps)),cuda=SimpleNamespace(is_available=lambda:cuda))
            with patch.dict(os.environ,{'PAPER_PEDIA_SPLADE_DEVICE':'auto'}): self.assertEqual(select_device(torch),expected)
        with patch.dict(os.environ,{'PAPER_PEDIA_SPLADE_DEVICE':'mps'}):
            with self.assertRaises(IndexFailure): select_device(torch)
    def test_chunks_include_entire_long_document(self):
        encoder=SpladeEncoder.__new__(SpladeEncoder);encoder.context=512
        class Tokenizer:
            def num_special_tokens_to_add(self,pair=False):return 2
            def build_inputs_with_special_tokens(self,ids):return [10000]+ids+[10001]
            def __call__(self,*args,**kwargs):return {'input_ids':list(range(1201))}
        encoder.tokenizer=Tokenizer()
        chunks=list(encoder._chunks(['long abstract']))
        self.assertEqual([len(row[1])-2 for row in chunks],[510,510,181])
        self.assertEqual([i for _,ids in chunks for i in ids[1:-1]],list(range(1201)))
        self.assertTrue(all(len(ids)<=512 for _,ids in chunks))
    def test_splade_build_rank_and_independent_status(self):
        info=service.build_collection_splade('AAAI',2026)
        self.assertTrue(info['indexed']);self.assertEqual(info['file'],'AAAI.2026__All.splade.sqlite3')
        self.assertEqual(service.collection_index_status('AAAI',2026)['state'],'missing')
        results=service.search_collection('AAAI',2026,'','graph graph',1,'splade')
        self.assertEqual(results[0]['paper_id'],'graphs');self.assertEqual(len(results),1)
        self.assertEqual(results[0]['score'],24)
    def test_splade_stale_and_reindex(self):
        service.build_collection_splade('AAAI',2026)
        save_papers_csv([self.rows[1]],self.path)
        self.assertEqual(service.collection_splade_status('AAAI',2026)['state'],'stale')
        with self.assertRaises(service.IndexUnavailable):service.search_collection('AAAI',2026,'','image',10,'splade')
        service.build_collection_splade('AAAI',2026,force=True)
        self.assertEqual(len(service.search_collection('AAAI',2026,'','image',10,'splade')),1)
    def test_failed_rebuild_preserves_index(self):
        service.build_collection_splade('AAAI',2026)
        path=splade.index_path(self.path,self.splade);before=path.read_bytes()
        with patch.object(self.encoder,'encode',side_effect=RuntimeError('test failure')):
            with self.assertRaises(service.IndexUnavailable):service.build_collection_splade('AAAI',2026,force=True)
        self.assertEqual(path.read_bytes(),before)
    def test_missing_partial_and_empty(self):
        with self.assertRaises(service.IndexUnavailable):service.search_collection('AAAI',2026,'','graph',10,'splade')
        partial=self.path.with_suffix('.partial.csv');save_papers_csv(self.rows,partial)
        with self.assertRaises(IndexFailure):splade.build_index(partial,self.splade,self.venues.parent/'models')
        save_papers_csv([],self.path);service.build_collection_splade('AAAI',2026)
        self.mock_encoder.assert_not_called()
        self.assertEqual(service.search_collection('AAAI',2026,'','graph',10,'splade'),[])
    def test_splade_collection_isolation(self):
        other=service.csv_path('ICLR',2024,'Spotlight');save_papers_csv([replace(self.rows[0],paper_id='different')],other)
        service.build_collection_splade('AAAI',2026);service.build_collection_splade('ICLR',2024,'Spotlight')
        self.assertEqual(service.search_collection('ICLR',2024,'Spotlight','graph',1,'splade')[0]['paper_id'],'different')
        self.assertNotEqual(service.search_collection('AAAI',2026,'','graph',1,'splade')[0]['paper_id'],'different')
    def test_jaccard_exact_set_formula(self):
        save_papers_csv([replace(self.rows[0],title='apple banana',abstract=''),replace(self.rows[1],title='apple banana cherry',abstract='')],self.path)
        service.build_collection_index('AAAI',2026)
        results=service.search_collection('AAAI',2026,'','apple apple date',2,'subset')
        self.assertAlmostEqual(results[0]['score'],1/3);self.assertAlmostEqual(results[1]['score'],1/4)
        self.assertEqual(service.search_collection('AAAI',2026,'','unrelated',10,'subset'),[])
    def test_jaccard_stemming_and_empty(self):
        save_papers_csv([replace(self.rows[0],title='Learning graphs',abstract='')],self.path)
        service.build_collection_index('AAAI',2026)
        self.assertEqual(service.search_collection('AAAI',2026,'','learned graph',10,'subset')[0]['score'],1)
        self.assertEqual(service.search_collection('AAAI',2026,'','the and',10,'subset'),[])
    def test_ui_radio_modes_and_splade_button(self):
        status,html=self.call('/search',query='venue=AAAI&year=2026&mode=splade')
        soup=BeautifulSoup(html,'html.parser')
        self.assertEqual(status,200)
        self.assertEqual({i['value'] for i in soup.select('input[type=radio][name=mode]')},{'dense','splade','sparse','subset'})
        self.assertEqual(soup.select_one('input[type=radio][checked]')['value'],'splade')
        self.assertIn('scheme=splade',html)
        self.assertEqual(self.call('/indices/build','POST','venue=AAAI&year=2026&scheme=splade')[0],303)
        status,html=self.call('/search',query='venue=AAAI&year=2026&mode=splade&q=graph&k=1')
        self.assertEqual(status,200);self.assertIn('Neural sparse (SPLADE)',html)
    def test_api_modes_and_validation(self):
        self.assertEqual(self.call('/api/venues/splade-index','POST','venue=AAAI&year=2026')[0],200)
        self.assertEqual(self.call('/api/venues/search',query='venue=AAAI&year=2026&mode=splade&q=graph&k=1')[0],200)
        self.assertEqual(self.call('/api/venues/search',query='venue=AAAI&year=2026&mode=invalid&q=graph')[0],422)
        self.assertEqual(self.call('/api/venues/search',query='venue=AAAI&year=2026&mode=subset&q=graph')[0],409)
        service.build_collection_index('AAAI',2026)
        self.assertEqual(self.call('/api/venues/search',query='venue=AAAI&year=2026&mode=subset&q=graph')[0],200)

    def test_masked_log_pooling(self):
        import torch
        from paper_pedia.index.splade_encoder import splade_pool
        logits=torch.tensor([[[-2.,3.,0.],[1.,2.,4.],[100.,100.,100.]]])
        pooled=splade_pool(logits,torch.tensor([[1,1,0]]))
        torch.testing.assert_close(pooled,torch.tensor([[math.log(2),math.log(4),math.log(5)]]))
    def test_sparse_persistence_and_large_query(self):
        import sqlite3
        vectors=[{i:2. for i in range(2000)},{3000:1.}]
        with patch.object(self.encoder,'encode',return_value=vectors):service.build_collection_splade('AAAI',2026)
        with sqlite3.connect(splade.index_path(self.path,self.splade)) as db:
            self.assertEqual(db.execute('SELECT COUNT(*) FROM postings').fetchone()[0],2001)
            self.assertEqual(db.execute('SELECT typeof(term),typeof(weight) FROM postings LIMIT 1').fetchone(),('integer','real'))
        with patch.object(self.encoder,'encode',return_value=[{i:3. for i in range(2000)}]):
            result=service.search_collection('AAAI',2026,'','expanded query',10,'splade')
        self.assertEqual(len(result),1);self.assertEqual(result[0]['score'],12000)
    def test_invalid_weights_preserve_index(self):
        service.build_collection_splade('AAAI',2026)
        path=splade.index_path(self.path,self.splade);before=path.read_bytes()
        for vector in [{0:float('nan')},{0:-1.},{-1:1.}]:
            with patch.object(self.encoder,'encode',return_value=[vector,vector]):
                with self.assertRaises(service.IndexUnavailable):service.build_collection_splade('AAAI',2026,force=True)
            self.assertEqual(path.read_bytes(),before)
    def test_ui_requires_selected_method_index(self):
        service.build_collection_index('AAAI',2026)
        for mode,disabled in [('splade',True),('sparse',False),('subset',False)]:
            status,html=self.call('/search',query='venue=AAAI&year=2026&mode='+mode)
            self.assertEqual(status,200)
            self.assertEqual(BeautifulSoup(html,'html.parser').select_one('[data-search-submit]').has_attr('disabled'),disabled)
        service.build_collection_splade('AAAI',2026)
        status,html=self.call('/search',query='venue=AAAI&year=2026&mode=splade')
        self.assertFalse(BeautifulSoup(html,'html.parser').select_one('[data-search-submit]').has_attr('disabled'))
    def test_acceleration_failure_retries_cpu(self):
        import threading
        encoder=SpladeEncoder.__new__(SpladeEncoder);encoder.device='mps';encoder.lock=threading.RLock()
        from unittest.mock import Mock
        encoder.model=Mock();encoder._encode=Mock(side_effect=[RuntimeError('device unavailable'),[{1:2.}]])
        self.assertEqual(encoder.encode(['test']),[{1:2.}]);self.assertEqual(encoder.device,'cpu')
        encoder.model.to.assert_called_once_with('cpu')

    def test_chunks_merge_by_max_not_sum(self):
        import torch
        encoder=SpladeEncoder.__new__(SpladeEncoder);encoder.torch=torch;encoder.device='cpu';encoder.batch_size=2
        encoder._chunks=lambda texts:iter([(0,[1,2]),(0,[3,4]),(1,[5])])
        class Tokenizer:
            def pad(self,inputs,**kwargs):
                n=len(inputs['input_ids'])
                return {'input_ids':torch.ones((n,2),dtype=torch.long),'attention_mask':torch.ones((n,2),dtype=torch.long)}
        encoder.tokenizer=Tokenizer()
        from unittest.mock import Mock
        encoder.model=Mock(side_effect=[SimpleNamespace(logits=torch.tensor([[[1.,0.],[0.,2.]],[[3.,0.],[0.,1.]]])),SimpleNamespace(logits=torch.tensor([[[0.,4.],[0.,0.]]]))])
        vectors=encoder._encode(['first','second'])
        self.assertAlmostEqual(vectors[0][0],math.log(4),places=6)
        self.assertAlmostEqual(vectors[0][1],math.log(3),places=6)
        self.assertEqual(set(vectors[1]),{1});self.assertAlmostEqual(vectors[1][1],math.log(5),places=6)
