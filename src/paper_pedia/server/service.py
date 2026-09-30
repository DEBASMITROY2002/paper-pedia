import hashlib, json, logging, re, time
from datetime import datetime, timezone
from threading import RLock
from functools import lru_cache
from urllib.parse import urlencode
from paper_pedia.scraper.papers_cool import PapersCoolScraper, ScrapeError
from paper_pedia.storage.csv_store import atomic_write, load_papers_csv, save_papers_csv
from paper_pedia import index as search_index
from paper_pedia.index import splade as splade_index, clip as clip_index, jaccard
from .config import CLIP_INDICES_DIR, CLIP_MODEL_DIR, CATALOG_CACHE, VENUES_DIR, INDICES_DIR, SPLADE_INDICES_DIR, SPLADE_MODEL_DIR
logger = logging.getLogger(__name__)
scraper = PapersCoolScraper()
lock = RLock()
@lru_cache(maxsize=None)
def collection_lock(path): return RLock()
class ServiceError(RuntimeError): pass
class SelectionError(ValueError): pass
class IndexUnavailable(ServiceError): pass
def _read_catalog():
    data = json.loads(CATALOG_CACHE.read_text(encoding="utf-8"))
    venues = data["venues"]
    if not isinstance(venues, dict) or not venues: raise ValueError("Empty catalog")
    for venue, years in venues.items():
        if not re.fullmatch(r"[A-Za-z0-9_-]+", venue) or not isinstance(years, dict): raise ValueError("Invalid venue")
        for year, groups in years.items():
            if not re.fullmatch(r"\d{4}", year) or not isinstance(groups, list) or any(not isinstance(g, str) for g in groups):
                raise ValueError("Invalid catalog entry")
    data.setdefault("updated_at", None)
    return data
def refresh_catalog():
    logger.info("Catalog refresh requested")
    started = time.perf_counter()
    with lock:
        logger.info("Catalog refresh started")
        try:
            venues = scraper.scrape_catalog()
            if not venues: raise ScrapeError("No venues returned; existing catalog preserved.")
            data = {"updated_at": datetime.now(timezone.utc).isoformat(), "source": "https://papers.cool/", "venues": venues}
            atomic_write(CATALOG_CACHE, lambda f: json.dump(data, f, ensure_ascii=False, indent=2))
            logger.info("Catalog refresh completed venues=%d editions=%d file=%s duration_ms=%.1f", len(venues), sum(len(y) for y in venues.values()), CATALOG_CACHE, (time.perf_counter() - started) * 1000)
            return data
        except (ScrapeError, OSError, ValueError) as exc:
            logger.exception("Catalog refresh failed; previous cache preserved file=%s", CATALOG_CACHE)
            raise ServiceError(str(exc)) from exc
def get_catalog(refresh=False):
    if refresh: return refresh_catalog()
    try:
        data = _read_catalog()
        logger.info("Catalog cache hit venues=%d file=%s", len(data["venues"]), CATALOG_CACHE)
        return data
    except FileNotFoundError:
        logger.info("Catalog cache miss file=%s", CATALOG_CACHE)
        return refresh_catalog()
    except (OSError, ValueError, KeyError, TypeError):
        logger.warning("Catalog cache unreadable; rebuilding file=%s", CATALOG_CACHE, exc_info=True)
        return refresh_catalog()
def csv_path(venue, year, group=""):
    if not re.fullmatch(r"[A-Za-z0-9_-]+", venue) or not 1900 <= int(year) <= 2200:
        raise SelectionError("Invalid venue or year.")
    suffix = re.sub(r"[^A-Za-z0-9._-]+", "_", group).strip("_") or "All"
    if group and (group == "All" or "_" in group or not re.fullmatch(r"[A-Za-z0-9. -]+", group)):
        suffix = suffix[:100] + "-" + hashlib.sha256(group.encode()).hexdigest()[:12]
    return VENUES_DIR / f"{venue}.{year}__{suffix}.csv"
def validate_selection(venue, year, group=""):
    csv_path(venue, year, group)
    years = get_catalog()["venues"].get(venue, {})
    if str(year) not in years or (group and group not in years[str(year)]):
        raise SelectionError("That venue, year, or group is not in the catalog. Refresh the catalog if needed.")
def get_papers(venue, year, group="", refresh=False):
    logger.info("Paper collection requested venue=%r year=%s group=%r refresh=%s; waiting for cache lock", venue, year, group or "All", refresh)
    started = time.perf_counter()
    with collection_lock(str(csv_path(venue, year, group))):
        validate_selection(venue, year, group)
        path = csv_path(venue, year, group)
        if path.exists() and not refresh:
            try:
                rows = load_papers_csv(path)
                logger.info("Paper cache hit papers=%d file=%s duration_ms=%.1f", len(rows), path, (time.perf_counter() - started) * 1000)
                return rows, path
            except (OSError, ValueError, KeyError, TypeError):
                logger.warning("Paper cache unreadable; rebuilding file=%s", path, exc_info=True)
        logger.info("Paper fetch started reason=%s venue=%r year=%s group=%r file=%s", "refresh" if refresh else "cache miss or invalid cache", venue, year, group or "All", path)
        checkpoint = path.with_suffix(".partial.csv")
        def save_checkpoint(papers):
            save_papers_csv(papers, checkpoint)
            logger.info("Paper checkpoint saved papers=%d file=%s", len(papers), checkpoint)
        try:
            papers = scraper.scrape_venue(f"{venue}.{year}", group, on_checkpoint=save_checkpoint)
            save_papers_csv(papers, path)
            rows = load_papers_csv(path)
            try: checkpoint.unlink(missing_ok=True)
            except OSError: logger.warning("Could not remove completed checkpoint file=%s", checkpoint, exc_info=True)
            logger.info("Paper cache saved papers=%d file=%s duration_ms=%.1f", len(rows), path, (time.perf_counter() - started) * 1000)
            return rows, path
        except (ScrapeError, OSError, ValueError, KeyError, TypeError) as exc:
            logger.exception("Paper fetch/cache operation failed file=%s", path)
            message = str(exc)
            if checkpoint.exists():
                message += f" Partial results are saved in {checkpoint.name}; retrying will start a fresh scrape."
            raise ServiceError(message) from exc
def cache_status(path):
    try:
        timestamp = datetime.fromtimestamp(path.stat().st_mtime, timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
        return {"cached": True, "updated_at": timestamp}
    except FileNotFoundError: return {"cached": False, "updated_at": None}
def cached_csvs(): return {p.name for p in VENUES_DIR.glob("*.csv") if not p.name.endswith(".partial.csv")}
def selection_query(venue, year, group=""):
    return urlencode({"venue": venue, "year": year, "group": group})
def catalog_cards(catalog):
    cards = []
    for venue, years in catalog.items():
        rows = []
        for year, groups in sorted(years.items(), reverse=True):
            for group in [""] + groups:
                rows.append({"year": year, "group": group, "query": selection_query(venue, year, group), **cache_status(csv_path(venue, year, group)), "index_info": search_index.index_status(csv_path(venue, year, group), INDICES_DIR), "clip_info": clip_index.index_status(csv_path(venue, year, group), CLIP_INDICES_DIR), "splade_info": splade_index.index_status(csv_path(venue, year, group), SPLADE_INDICES_DIR)})
        cards.append({"venue": venue, "years": len(years), "rows": rows})
    return cards

def collection_index_status(venue, year, group=""):
    validate_selection(venue, year, group)
    return search_index.index_status(csv_path(venue, year, group), INDICES_DIR)
def build_collection_index(venue, year, group="", force=False):
    with collection_lock(str(csv_path(venue, year, group))):
        validate_selection(venue, year, group)
        try: return search_index.build_index(csv_path(venue, year, group), INDICES_DIR, force)
        except search_index.IndexFailure as exc: raise IndexUnavailable(str(exc)) from exc
def search_collection(venue, year, group, query, k=10, mode="sparse"):
    with collection_lock(str(csv_path(venue, year, group))):
        validate_selection(venue, year, group)
        try:
            path = csv_path(venue, year, group)
            if mode == "dense": return clip_index.search(path, CLIP_INDICES_DIR, CLIP_MODEL_DIR, query, k)
            if mode == "splade": return splade_index.search(path, SPLADE_INDICES_DIR, SPLADE_MODEL_DIR, query, k)
            if mode == "subset": return jaccard.search(path, INDICES_DIR, query, k)
            if mode != "sparse": raise SelectionError("Unknown search method.")
            return search_index.search(path, INDICES_DIR, query, k)
        except search_index.IndexFailure as exc: raise IndexUnavailable(str(exc)) from exc

def collection_splade_status(venue, year, group=""):
    validate_selection(venue, year, group)
    return splade_index.index_status(csv_path(venue, year, group), SPLADE_INDICES_DIR)
def build_collection_splade(venue, year, group="", force=False):
    with collection_lock(str(csv_path(venue, year, group))):
        validate_selection(venue, year, group)
        try: return splade_index.build_index(csv_path(venue, year, group), SPLADE_INDICES_DIR, SPLADE_MODEL_DIR, force)
        except search_index.IndexFailure as exc: raise IndexUnavailable(str(exc)) from exc

def collection_clip_status(venue, year, group=""):
    validate_selection(venue, year, group)
    return clip_index.index_status(csv_path(venue, year, group), CLIP_INDICES_DIR)
def build_collection_clip(venue, year, group="", force=False):
    with collection_lock(str(csv_path(venue, year, group))):
        validate_selection(venue, year, group)
        try: return clip_index.build_index(csv_path(venue, year, group), CLIP_INDICES_DIR, CLIP_MODEL_DIR, force)
        except search_index.IndexFailure as exc: raise IndexUnavailable(str(exc)) from exc
