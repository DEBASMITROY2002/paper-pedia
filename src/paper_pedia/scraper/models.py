from dataclasses import dataclass
from typing import List

@dataclass
class Paper:
    paper_id: str
    index: int
    venue: str
    conference: str
    year: int
    group: str
    title: str
    authors: List[str]
    author_links: List[str]
    abstract: str
    keywords: List[str]
    official_url: str
    papers_cool_url: str
    pdf_url: str
    subject: str
    subject_url: str