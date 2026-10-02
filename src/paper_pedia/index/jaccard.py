from .memory import operation
import heapq, json, logging, sqlite3, time
from contextlib import closing
from functools import lru_cache
from pathlib import Path
from .tfidf import IndexFailure, index_status, index_path, _query_counts, _connect
logger = logging.getLogger(__name__)
def _sizes(path, signature):
    with closing(_connect(path)) as db:
        return dict(db.execute("SELECT doc,COUNT(*) FROM postings GROUP BY doc"))
@operation
def search(csv_path, directory, query, k=10, exclude=""):
    if len(exclude) > 1000: raise ValueError("Exclude concepts must be at most 1000 characters.")
    if not 1 <= k <= 100 or not query.strip() or len(query) > 1000: raise ValueError("Enter a valid query and top k between 1 and 100.")
    if not index_status(csv_path, directory)["indexed"]: raise IndexFailure("Build or refresh the TF-IDF index before Subset (Jaccard) search.")
    started, terms = time.perf_counter(), set(_query_counts(query))
    excluded = set(_query_counts(exclude))
    if not terms or terms == excluded: return []
    path = index_path(csv_path, directory)
    try:
        stat = path.stat()
        sizes = _sizes(str(path), (stat.st_mtime_ns, stat.st_ctime_ns, stat.st_size))
        with closing(_connect(path)) as db:
            db.execute("CREATE TEMP TABLE query (term TEXT PRIMARY KEY, included INTEGER, excluded INTEGER)")
            db.executemany("INSERT INTO query VALUES (?,?,?)", ((term, int(term in terms), int(term in excluded)) for term in terms | excluded))
            matches = db.execute("SELECT p.doc,SUM(q.included),SUM(q.excluded) FROM postings p JOIN query q ON p.term=q.term GROUP BY p.doc HAVING SUM(q.included)>0")
            def candidates():
                for doc, overlap, penalty in matches:
                    score = overlap / (sizes[doc] + len(terms) - overlap)
                    if excluded: score -= penalty / (sizes[doc] + len(excluded) - penalty)
                    if score > 0: yield -score, doc
            ranked = heapq.nsmallest(k, candidates())
            results = [{**json.loads(db.execute("SELECT data FROM documents WHERE doc=?", (doc,)).fetchone()[0]), "score": -score} for score, doc in ranked]
        logger.info("Jaccard search completed collection=%s query_terms=%d returned=%d duration_ms=%.1f", Path(csv_path).name, len(terms), len(results), (time.perf_counter() - started) * 1000)
        return results
    except (OSError, sqlite3.Error, ValueError, KeyError, TypeError) as exc:
        logger.exception("Jaccard search failed file=%s", path)
        raise IndexFailure("Jaccard search failed. Reindex TF-IDF for this collection.") from exc
