import heapq, json, logging, sqlite3, time
from contextlib import closing
from functools import lru_cache
from pathlib import Path
from .tfidf import IndexFailure, index_status, index_path, _query_counts, _connect
logger = logging.getLogger(__name__)
@lru_cache(maxsize=4)
def _sizes(path, signature):
    with closing(_connect(path)) as db:
        return dict(db.execute("SELECT doc,COUNT(*) FROM postings GROUP BY doc"))
def search(csv_path, directory, query, k=10):
    if not 1 <= k <= 100 or not query.strip() or len(query) > 1000: raise ValueError("Enter a valid query and top k between 1 and 100.")
    if not index_status(csv_path, directory)["indexed"]: raise IndexFailure("Build or refresh the TF-IDF index before Subset (Jaccard) search.")
    started, terms = time.perf_counter(), set(_query_counts(query))
    if not terms: return []
    path = index_path(csv_path, directory)
    try:
        stat = path.stat()
        sizes = _sizes(str(path), (stat.st_mtime_ns, stat.st_ctime_ns, stat.st_size))
        with closing(_connect(path)) as db:
            slots = ",".join("?" for _ in terms)
            matches = db.execute(f"SELECT doc,COUNT(*) FROM postings WHERE term IN ({slots}) GROUP BY doc", tuple(terms))
            ranked = heapq.nsmallest(k, ((-(overlap / (sizes[doc] + len(terms) - overlap)), doc) for doc, overlap in matches))
            results = [{**json.loads(db.execute("SELECT data FROM documents WHERE doc=?", (doc,)).fetchone()[0]), "score": -score} for score, doc in ranked]
        logger.info("Jaccard search completed collection=%s query_terms=%d returned=%d duration_ms=%.1f", Path(csv_path).name, len(terms), len(results), (time.perf_counter() - started) * 1000)
        return results
    except (OSError, sqlite3.Error, ValueError, KeyError, TypeError) as exc:
        logger.exception("Jaccard search failed file=%s", path)
        raise IndexFailure("Jaccard search failed. Reindex TF-IDF for this collection.") from exc
