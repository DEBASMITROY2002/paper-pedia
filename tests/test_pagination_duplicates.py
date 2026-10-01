import unittest
from dataclasses import replace
from unittest.mock import patch
import test_project
from paper_pedia.scraper.papers_cool import PapersCoolScraper, ScrapeError
class DuplicatePaginationTests(unittest.TestCase):
    setUp = test_project.ProjectTests.setUp
    def scrape(self, pages):
        scraper=PapersCoolScraper(delay=0)
        with patch.object(scraper,'_fetch_page',return_value='html') as fetch, patch.object(scraper,'_parse_page',side_effect=pages):
            rows=scraper.scrape_venue('CVPR.2025')
        return rows,[c.args[2] for c in fetch.call_args_list]
    def test_single_response_duplicate_id(self):
        a,b=self.papers
        rows,offsets=self.scrape([([a,b,a],3)])
        self.assertEqual([p.paper_id for p in rows],[a.paper_id,b.paper_id])
        self.assertEqual(offsets,[0])
    def test_exact_reported_counts(self):
        rows=[replace(self.papers[0],paper_id=str(i)) for i in range(2870)]
        result,offsets=self.scrape([(rows+[rows[0]],2871)])
        self.assertEqual(len(result),2870); self.assertEqual(offsets,[0])
    def test_overlap_advances_by_entries(self):
        a,b=self.papers; c=replace(a,paper_id='third')
        rows,offsets=self.scrape([([a,b],4),([b,c],4)])
        self.assertEqual(len(rows),3); self.assertEqual(offsets,[0,2])
    def test_unique_count_can_differ_before_last_page(self):
        a,b=self.papers; c=replace(a,paper_id='third')
        rows,offsets=self.scrape([([a,a],4),([b],4),([c],4)])
        self.assertEqual(len(rows),3); self.assertEqual(offsets,[0,2,3])
    def test_duplicate_only_different_page_is_not_stalled(self):
        a,b=self.papers; c=replace(a,paper_id='third'); d=replace(a,paper_id='fourth')
        rows,offsets=self.scrape([([a,b,c],6),([a,b],6),([d],6)])
        self.assertEqual(len(rows),4); self.assertEqual(offsets,[0,3,5])
    def test_full_page_repeat_is_still_rejected(self):
        a,b=self.papers
        with self.assertRaisesRegex(ScrapeError,'repeated an entire page'):
            self.scrape([([a,b],4),([a,b],4)])
    def test_changing_total_is_rejected(self):
        a,b=self.papers
        with self.assertRaisesRegex(ScrapeError,'total changed'):
            self.scrape([([a],2),([b],3)])
