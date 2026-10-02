from .memory import operation
import heapq, json, logging, os, sqlite3, tempfile, time
from contextlib import closing
from datetime import datetime, timezone
from functools import lru_cache
from pathlib import Path
from paper_pedia.storage.csv_store import load_papers_csv
from .tfidf import IndexFailure, fingerprint, _connect, _metadata, _status
from .clip_encoder import get_encoder, MODEL, REVISION, VERSION, clean_text
logger = logging.getLogger(__name__)
SCHEMA = 1
def index_path(csv_path, directory): return Path(directory) / (Path(csv_path).stem + ".clip.sqlite3")
def index_status(csv_path, directory):
    path = index_path(csv_path, directory)
    if not Path(csv_path).exists(): return _status("uncached")
    if not path.exists(): return _status("missing")
    try:
        with closing(_connect(path)) as db: meta = _metadata(db)
        fresh = meta["source_sha256"] == fingerprint(csv_path) and meta["schema"] == SCHEMA and meta["normalization"] == VERSION and meta["model"] == MODEL and meta["revision"] == REVISION
        return _status("indexed" if fresh else "stale", updated_at=meta["updated_at"], count=meta["count"], device=meta["device"], file=path.name)
    except (OSError, sqlite3.Error, ValueError, TypeError, KeyError, IndexError):
        logger.warning("CLIP index unreadable file=%s", path, exc_info=True)
        return _status("invalid")
@operation
def build_index(csv_path, directory, model_dir, force=False):
    csv_path = Path(csv_path)
    if csv_path.name.endswith(".partial.csv"): raise IndexFailure("Finish rendering before building a CLIP index.")
    state = index_status(csv_path, directory)
    if state["state"] == "uncached": raise IndexFailure("Render this collection before CLIP indexing.")
    if state["indexed"] and not force: return state
    started, path, temp = time.perf_counter(), index_path(csv_path, directory), None
    logger.info("CLIP index build started source=%s", csv_path)
    try:
        import numpy as np
        source_hash = fingerprint(csv_path)
        papers = load_papers_csv(csv_path)
        encoder = get_encoder(str(model_dir)) if papers else None
        vectors = encoder.encode([paper["title"] + ". " + paper["abstract"] for paper in papers]) if papers else np.zeros((0, 512), dtype=np.float32)
        path.parent.mkdir(parents=True, exist_ok=True)
        handle, name = tempfile.mkstemp(prefix=path.stem + ".", suffix=".tmp", dir=path.parent)
        os.close(handle)
        temp = Path(name)
        with closing(sqlite3.connect(temp)) as db:
            db.executescript("CREATE TABLE documents (doc INTEGER PRIMARY KEY, data TEXT NOT NULL, vector BLOB NOT NULL); CREATE TABLE metadata (key TEXT PRIMARY KEY, value TEXT NOT NULL);")
            db.executemany("INSERT INTO documents VALUES (?,?,?)", ((i, json.dumps(paper, ensure_ascii=False), vectors[i].astype("<f4").tobytes()) for i, paper in enumerate(papers)))
            meta = {"schema": SCHEMA, "normalization": VERSION, "source_sha256": source_hash, "count": len(papers), "dimension": vectors.shape[1], "model": MODEL, "revision": REVISION, "device": encoder.device if encoder else "none", "updated_at": datetime.now(timezone.utc).isoformat()}
            db.execute("INSERT INTO metadata VALUES ('index',?)", (json.dumps(meta),))
            db.commit()
        if fingerprint(csv_path) != source_hash: raise IndexFailure("The CSV changed during CLIP indexing. Retry Reindex CLIP.")
        os.replace(temp, path)
        logger.info("CLIP index completed papers=%d device=%s file=%s duration_ms=%.1f", len(papers), meta["device"], path, (time.perf_counter() - started) * 1000)
        return index_status(csv_path, directory)
    except IndexFailure: raise
    except Exception as exc:
        logger.exception("CLIP indexing failed; previous index preserved source=%s", csv_path)
        raise IndexFailure("CLIP indexing failed. Check server logs and retry.") from exc
    finally:
        if temp and temp.exists(): temp.unlink()
@operation
def search(csv_path, directory, model_dir, query, k=10, exclude=""):
    if len(exclude) > 1000: raise ValueError("Exclude concepts must be at most 1000 characters.")
    if not 1 <= k <= 100 or not query.strip() or len(query) > 1000: raise ValueError("Enter a query (1–1000 characters) and top k between 1 and 100.")
    if not index_status(csv_path, directory)["indexed"]: raise IndexFailure("Build or refresh this collection's CLIP index before Dense search.")
    started, path = time.perf_counter(), index_path(csv_path, directory)
    try:
        import numpy as np
        if not clean_text(query): return []
        best = []
        with closing(_connect(path)) as db:
            meta = _metadata(db)
            if not meta['count']: return []
            encoder = get_encoder(str(model_dir))
            vectors = encoder.encode([query, exclude] if clean_text(exclude) else [query])
            needle = vectors[0] - vectors[1] if len(vectors) == 2 else vectors[0]
            if not np.any(needle): return []
            cursor = db.execute('SELECT doc,vector FROM documents ORDER BY doc')
            count = 0
            while rows := cursor.fetchmany(256):
                matrix = np.stack([np.frombuffer(row[1], dtype='<f4') for row in rows])
                if matrix.shape[1] != meta['dimension'] or not np.isfinite(matrix).all(): raise IndexFailure('Invalid CLIP index. Reindex this collection.')
                scores = encoder.scores(matrix, needle)
                if not np.isfinite(scores).all(): raise IndexFailure('Invalid CLIP scores.')
                for (doc, _), score in zip(rows, scores):
                    candidate = (float(score), -doc)
                    if len(best) < k: heapq.heappush(best, candidate)
                    elif candidate > best[0]: heapq.heapreplace(best, candidate)
                count += len(rows)
                del matrix, scores, rows
            if count != meta['count']: raise IndexFailure('Incomplete CLIP index. Reindex this collection.')
            results = [{**json.loads(db.execute('SELECT data FROM documents WHERE doc=?', (-doc,)).fetchone()[0]), 'score': score} for score, doc in sorted(best, reverse=True)]
        logger.info("CLIP search completed collection=%s returned=%d device=%s duration_ms=%.1f", Path(csv_path).name, len(results), encoder.device, (time.perf_counter() - started) * 1000)
        return results
    except IndexFailure: raise
    except Exception as exc:
        logger.exception("CLIP search failed file=%s", path)
        raise IndexFailure("CLIP search failed. Check server logs and try Reindex CLIP.") from exc
