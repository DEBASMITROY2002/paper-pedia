import logging, re, time, threading
from urllib.parse import parse_qs, quote, urljoin, urlparse
import requests
from bs4 import BeautifulSoup
from .models import Paper
logger = logging.getLogger(__name__)
BASE_URL = "https://papers.cool"
class ScrapeError(RuntimeError): pass
class PapersCoolScraper:
    def __init__(self, page_size=10000, delay=0.75):
        self.page_size, self.delay = page_size, delay
        self._sessions = threading.local()
    @property
    def session(self):
        if not hasattr(self._sessions, 'value'):
            self._sessions.value = requests.Session()
            self._sessions.value.headers['User-Agent'] = 'PaperPedia/0.2 (personal academic paper index)'
        return self._sessions.value
    def _get(self, url, params=None):
        started = time.perf_counter()
        logger.debug("Upstream request url=%s params=%r", url, params)
        try:
            response = self.session.get(url, params=params, timeout=(10, 45))
            logger.debug("Upstream response status=%d duration_ms=%.1f", response.status_code, (time.perf_counter() - started) * 1000)
            response.raise_for_status()
            return response.text
        except requests.RequestException as exc:
            raise ScrapeError("Papers Cool could not be reached. Try again later; existing caches are preserved.") from exc
    def scrape_catalog(self):
        logger.info("Discovering venue catalog source=%s", BASE_URL)
        catalog = self._parse_catalog(self._get(BASE_URL))
        if not catalog: raise ScrapeError("No venues found; the source page may have changed. Existing catalog preserved.")
        logger.info("Catalog discovery completed venues=%d", len(catalog))
        return catalog
    @staticmethod
    def _parse_catalog(html):
        catalog = {}
        for a in BeautifulSoup(html, "html.parser").select('a[href*="/venue/"]'):
            url = urlparse(urljoin(BASE_URL, a.get("href", "")))
            match = re.fullmatch(r"/venue/([A-Za-z0-9_-]+)\.(\d{4})/?", url.path)
            if url.netloc != "papers.cool" or not match: continue
            venue, year = match.groups()
            groups = catalog.setdefault(venue, {}).setdefault(year, [])
            group = parse_qs(url.query).get("group", [""])[0]
            if group and group not in groups: groups.append(group)
        return {v: {y: sorted(gs) for y, gs in sorted(ys.items(), reverse=True)} for v, ys in sorted(catalog.items(), key=lambda item: item[0].lower())}
    def scrape_venue(self, venue, group="", on_checkpoint=None):
        if not re.fullmatch(r"[A-Za-z0-9_-]+\.\d{4}", venue): raise ValueError("Invalid venue/year.")
        started = time.perf_counter()
        logger.info("Scrape started venue=%r group=%r page_size=%d", venue, group or "All", self.page_size)
        papers, seen, page_signatures, skip, total = [], set(), set(), 0, None
        for _ in range(10000):
            page, page_total = self._parse_page(self._fetch_page(venue, group, skip), venue, group)
            if total is None:
                total = page_total
                if total is None: raise ScrapeError("Paper total is missing; refusing to cache a possibly incomplete response.")
            elif page_total is not None and page_total != total:
                raise ScrapeError("The source total changed during pagination. Retry to get a consistent collection.")
            signature = tuple(p.paper_id for p in page)
            if page and signature in page_signatures:
                raise ScrapeError("The source repeated an entire page without advancing. Existing cache preserved.")
            page_signatures.add(signature)
            before = len(papers)
            for paper in page:
                if paper.paper_id not in seen:
                    seen.add(paper.paper_id)
                    papers.append(paper)
                    if on_checkpoint and len(papers) % 500 == 0:
                        on_checkpoint(papers)
            fetched = skip + len(page)
            duplicates = len(page) - (len(papers) - before)
            if duplicates:
                logger.warning("Duplicate paper entries removed venue=%r group=%r offset=%d duplicates=%d", venue, group or "All", skip, duplicates)
            logger.info("Scrape progress venue=%r group=%r offset=%d received=%d fetched=%d unique=%d total_entries=%d", venue, group or "All", skip, len(page), fetched, len(papers), total)
            # The source total and skip count entries, including repeated paper IDs.
            if fetched >= total:
                logger.info("Scrape completed venue=%r group=%r papers=%d fetched=%d duplicates=%d duration_ms=%.1f", venue, group or "All", len(papers), fetched, fetched - len(papers), (time.perf_counter() - started) * 1000)
                return papers
            if not page:
                raise ScrapeError("Pagination stopped making progress before all entries arrived. Existing cache preserved.")
            skip = fetched
            time.sleep(self.delay)
        raise ScrapeError("Pagination limit exceeded; existing cache preserved.")
    def _fetch_page(self, venue, group, skip):
        params = {"show": self.page_size, "skip": skip}
        if group: params["group"] = group
        logger.info("Fetching paper page venue=%r group=%r offset=%d limit=%d", venue, group or "All", skip, self.page_size)
        return self._get(f"{BASE_URL}/venue/{quote(venue)}", params)
    def _parse_page(self, html, venue, group):
        soup = BeautifulSoup(html, "html.parser")
        conference, year = venue.rsplit(".", 1)
        papers = [self._parse_paper(card, venue, conference, int(year), group) for card in soup.select("div.papers div.paper")]
        return papers, self._extract_total(soup)
    def _parse_paper(self, card, venue, conference, year, group):
        title = card.select_one("a.title-link")
        if title is None or not card.get("id"): raise ScrapeError("Paper markup changed; existing cache preserved.")
        def text(selector):
            el = card.select_one(selector)
            return el.get_text(" ", strip=True) if el else ""
        def link(selector, attr="href"):
            el = card.select_one(selector)
            value = el.get(attr, "") if el else ""
            return urljoin(BASE_URL, value) if value else ""
        authors = card.select("a.author")
        index = re.search(r"\d+", text("span.index"))
        return Paper(paper_id=card["id"], index=int(index.group()) if index else 0,
            venue=venue, conference=conference, year=year, group=group,
            title=title.get_text(" ", strip=True), authors=[a.get_text(" ", strip=True) for a in authors],
            author_links=[urljoin(BASE_URL, a.get("href", "")) for a in authors], abstract=text("p.summary"),
            keywords=[k.strip() for k in card.get("keywords", "").split(",") if k.strip()],
            official_url=link("h2.title > a:first-child"), papers_cool_url=link("a.title-link"),
            pdf_url=link("a.title-pdf", "data"), subject=text("p.subjects a"), subject_url=link("p.subjects a"))
    @staticmethod
    def _extract_total(soup):
        info = soup.select_one("p.info")
        match = re.search(r"Total:\s*([\d,]+)", info.get_text(" ", strip=True)) if info else None
        return int(match.group(1).replace(",", "")) if match else None
