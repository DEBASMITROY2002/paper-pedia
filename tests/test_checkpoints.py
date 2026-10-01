import asyncio, json, tempfile, unittest
from dataclasses import replace
from pathlib import Path
from unittest.mock import patch
from bs4 import BeautifulSoup
from paper_pedia.server import service
from paper_pedia.scraper.papers_cool import ScrapeError
from paper_pedia.storage.csv_store import load_papers_csv, save_papers_csv
import test_project
class CheckpointTests(unittest.TestCase):
    setUp = test_project.ProjectTests.setUp
    call = test_project.ProjectTests.call
    def test_checkpoints_every_500_and_final_csv(self):
        rows=[replace(self.papers[0],paper_id=str(i),index=i+1) for i in range(1051)]
        counts=[]
        def save(papers,path):
            save_papers_csv(papers,path)
            if path.name.endswith('.partial.csv'): counts.append(len(load_papers_csv(path)))
        with patch.object(service.scraper,'_fetch_page',return_value='html'), patch.object(service.scraper,'_parse_page',side_effect=[(rows[:500],1051),(rows[500:1000],1051),(rows[1000:],1051)]), patch.object(service.scraper,'delay',0), patch.object(service,'save_papers_csv',side_effect=save):
            result,path=service.get_papers('AAAI',2026)
        self.assertEqual(counts,[500,1000])
        self.assertEqual(len(result),1051)
        self.assertFalse(path.with_suffix('.partial.csv').exists())
    def test_interruption_keeps_checkpoint_and_previous_cache(self):
        path=service.csv_path('AAAI',2026)
        save_papers_csv(self.papers,path)
        before=path.read_bytes()
        rows=[replace(self.papers[0],paper_id=str(i)) for i in range(500)]
        with patch.object(service.scraper,'_fetch_page',side_effect=['html',ScrapeError('Connection lost')]), patch.object(service.scraper,'_parse_page',return_value=(rows,900)), patch.object(service.scraper,'delay',0):
            with self.assertRaisesRegex(service.ServiceError,'Partial results are saved'):
                service.get_papers('AAAI',2026,refresh=True)
        self.assertEqual(path.read_bytes(),before)
        self.assertEqual(len(load_papers_csv(path.with_suffix('.partial.csv'))),500)
    def test_render_count_popup(self):
        save_papers_csv(self.papers,service.csv_path('AAAI',2026))
        status,html=self.call('/papers',query='venue=AAAI&year=2026')
        dialog=BeautifulSoup(html,'html.parser').select_one('dialog#render-result')
        self.assertEqual(status,200)
        self.assertIn('2 papers rendered',dialog.get_text())
        self.assertIsNotNone(dialog.select_one('form[method="dialog"] button'))
        status,html=self.call('/papers',query='venue=AAAI&year=2026&group=invalid')
        self.assertEqual(status,404)
        self.assertNotIn('id="render-result"',html)
