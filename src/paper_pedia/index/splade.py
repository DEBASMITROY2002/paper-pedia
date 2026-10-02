from .memory import operation
import json, logging, math, os, sqlite3, tempfile, time
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path
from paper_pedia.storage.csv_store import load_papers_csv
from .tfidf import IndexFailure, fingerprint, _connect, _metadata, _status
from .splade_encoder import get_encoder, MODEL, REVISION, VERSION, clean_text
logger = logging.getLogger(__name__)
SCHEMA = 1
def index_path(csv_path, directory): return Path(directory) / (Path(csv_path).stem + ".splade.sqlite3")
def index_status(csv_path, directory):
    path = index_path(csv_path, directory)
    if not Path(csv_path).exists(): return _status("uncached")
    if not path.exists(): return _status("missing")
    try:
        with closing(_connect(path)) as db: meta = _metadata(db)
        fresh = meta["source_sha256"] == fingerprint(csv_path) and meta["schema"] == SCHEMA and meta["normalization"] == VERSION and meta["model"] == MODEL and meta["revision"] == REVISION and meta["scoring"] == "dot_product"
        return _status("indexed" if fresh else "stale", updated_at=meta["updated_at"], count=meta["count"], device=meta["device"], file=path.name)
    except (OSError, sqlite3.Error, ValueError, TypeError, KeyError, IndexError):
        logger.warning("SPLADE index unreadable file=%s", path, exc_info=True)
        return _status("invalid")
def _validate(weights):
    if any(not isinstance(term, int) or term < 0 or not math.isfinite(value) or value <= 0 for term, value in weights.items()):
        raise IndexFailure("Invalid SPLADE term weights; previous index preserved.")
@operation
def build_index(csv_path, directory, model_dir, force=False):
    csv_path = Path(csv_path)
    if csv_path.name.endswith(".partial.csv"): raise IndexFailure("Finish rendering before building a SPLADE index.")
    state = index_status(csv_path, directory)
    if state["state"] == "uncached": raise IndexFailure("Render this collection before SPLADE indexing.")
    if state["indexed"] and not force: return state
    started, path, temp = time.perf_counter(), index_path(csv_path, directory), None
    logger.info("SPLADE index build started source=%s", csv_path)
    try:
        source_hash = fingerprint(csv_path)
        papers = load_papers_csv(csv_path)
        encoder = get_encoder(str(model_dir)) if papers else None
        path.parent.mkdir(parents=True, exist_ok=True)
        handle, name = tempfile.mkstemp(prefix=path.stem + ".", suffix=".tmp", dir=path.parent)
        os.close(handle)
        temp = Path(name)
        with closing(sqlite3.connect(temp)) as db:
            db.executescript("CREATE TABLE documents (doc INTEGER PRIMARY KEY, data TEXT NOT NULL); CREATE TABLE postings (term INTEGER NOT NULL, doc INTEGER NOT NULL, weight REAL NOT NULL, PRIMARY KEY(term,doc)) WITHOUT ROWID; CREATE TABLE metadata (key TEXT PRIMARY KEY, value TEXT NOT NULL);")
            for start in range(0, len(papers), 32):
                batch = papers[start:start + 32]
                vectors = encoder.encode([paper["title"] + ". " + paper["abstract"] for paper in batch])
                if len(vectors) != len(batch): raise IndexFailure("SPLADE returned an incomplete batch; previous index preserved.")
                for doc, (paper, weights) in enumerate(zip(batch, vectors), start):
                    _validate(weights)
                    db.execute("INSERT INTO documents VALUES (?,?)", (doc, json.dumps(paper, ensure_ascii=False)))
                    db.executemany("INSERT INTO postings VALUES (?,?,?)", ((term, doc, value) for term, value in weights.items()))
                if (start + len(batch)) % 128 == 0 or start + len(batch) == len(papers):
                    logger.info("SPLADE index progress papers=%d total=%d device=%s", start + len(batch), len(papers), encoder.device)
            meta = {"schema": SCHEMA, "normalization": VERSION, "source_sha256": source_hash, "count": len(papers), "dimension": encoder.dimension if encoder else 30522, "model": MODEL, "revision": REVISION, "scoring": "dot_product", "device": encoder.device if encoder else "none", "updated_at": datetime.now(timezone.utc).isoformat()}
            db.execute("INSERT INTO metadata VALUES ('index',?)", (json.dumps(meta),))
            db.commit()
        if fingerprint(csv_path) != source_hash: raise IndexFailure("The CSV changed during SPLADE indexing. Retry Reindex SPLADE.")
        os.replace(temp, path)
        logger.info("SPLADE index completed papers=%d device=%s file=%s duration_ms=%.1f", len(papers), meta["device"], path, (time.perf_counter() - started) * 1000)
        return index_status(csv_path, directory)
    except IndexFailure: raise
    except Exception as exc:
        logger.exception("SPLADE indexing failed; previous index preserved source=%s", csv_path)
        raise IndexFailure("SPLADE indexing failed. Check server logs and retry.") from exc
    finally:
        if temp and temp.exists(): temp.unlink()
@operation
def search(csv_path, directory, model_dir, query, k=10):
    if not 1 <= k <= 100 or not query.strip() or len(query) > 1000: raise ValueError("Enter a query (1–1000 characters) and top k between 1 and 100.")
    state = index_status(csv_path, directory)
    if not state["indexed"]: raise IndexFailure("Build or refresh this collection's SPLADE index before searching.")
    if not state["count"] or not clean_text(query): return []
    started, path = time.perf_counter(), index_path(csv_path, directory)
    try:
        encoder = get_encoder(str(model_dir))
        weights = encoder.encode([query])[0]
        _validate(weights)
        if not weights: return []
        with closing(_connect(path)) as db:
            # A temporary query table avoids SQLite parameter limits for expanded queries.
            db.execute("CREATE TEMP TABLE query (term INTEGER PRIMARY KEY, weight REAL NOT NULL)")
            db.executemany("INSERT INTO query VALUES (?,?)", weights.items())
            rows = db.execute("WITH ranked AS (SELECT p.doc,SUM(p.weight*q.weight) AS score FROM query q CROSS JOIN postings p ON p.term=q.term GROUP BY p.doc ORDER BY score DESC,p.doc LIMIT ?) SELECT d.data,r.score FROM ranked r JOIN documents d ON d.doc=r.doc ORDER BY r.score DESC,r.doc", (k,))
            results = [{**json.loads(data), "score": score} for data, score in rows]
        logger.info("SPLADE search completed collection=%s expanded_terms=%d returned=%d device=%s duration_ms=%.1f", Path(csv_path).name, len(weights), len(results), encoder.device, (time.perf_counter() - started) * 1000)
        return results
    except IndexFailure: raise
    except Exception as exc:
        logger.exception("SPLADE search failed file=%s", path)
        raise IndexFailure("SPLADE search failed. Check server logs and try Reindex SPLADE.") from exc
