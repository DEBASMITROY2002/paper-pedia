import hashlib, itertools, json, logging, math, os, sqlite3, tempfile, time
from contextlib import closing
from datetime import datetime, timezone
from functools import lru_cache
from pathlib import Path
from paper_pedia.storage.csv_store import load_papers_csv
from .preprocess import normalize, TOKENIZER, VERSION
logger = logging.getLogger(__name__)
SCHEMA = 1
class IndexFailure(RuntimeError): pass
def index_path(csv_path, directory): return Path(directory) / (Path(csv_path).stem + ".tfidf.sqlite3")
@lru_cache(maxsize=256)
def _digest(path, signature):
    digest = hashlib.sha256()
    with Path(path).open("rb") as file:
        for chunk in iter(lambda: file.read(1024 * 1024), b""): digest.update(chunk)
    return digest.hexdigest()
def fingerprint(path):
    path = Path(path).resolve()
    stat = path.stat()
    return _digest(str(path), (stat.st_size, stat.st_mtime_ns, stat.st_ctime_ns, stat.st_ino))
def _connect(path):
    return sqlite3.connect(Path(path).resolve().as_uri() + "?mode=ro", uri=True)
def _metadata(db): return json.loads(db.execute("SELECT value FROM metadata WHERE key='index'").fetchone()[0])
def _status(state, **extra):
    return {"state": state, "indexed": state == "indexed", "label": {"uncached":"Render first", "missing":"Not indexed", "indexed":"Indexed", "stale":"Needs reindex", "invalid":"Index unreadable"}[state], **extra}
def index_status(csv_path, directory):
    path = index_path(csv_path, directory)
    if not Path(csv_path).exists(): return _status("uncached")
    if not path.exists(): return _status("missing")
    try:
        with closing(_connect(path)) as db: meta = _metadata(db)
        fresh = meta["source_sha256"] == fingerprint(csv_path) and meta["schema"] == SCHEMA and meta["normalization"] == VERSION
        return _status("indexed" if fresh else "stale", updated_at=meta["updated_at"], count=meta["count"], file=path.name)
    except (OSError, sqlite3.Error, ValueError, TypeError, KeyError, IndexError):
        logger.warning("Index unreadable file=%s", path, exc_info=True)
        return _status("invalid")
def _create_tokens(db):
    db.execute(f"CREATE VIRTUAL TABLE corpus USING fts5(text, content='', tokenize='{TOKENIZER}')")
    db.execute("CREATE VIRTUAL TABLE vocabulary USING fts5vocab(corpus, 'row')")
def build_index(csv_path, directory, force=False):
    csv_path = Path(csv_path)
    if csv_path.name.endswith(".partial.csv"): raise IndexFailure("Partial CSVs cannot be indexed. Finish rendering first.")
    state = index_status(csv_path, directory)
    if state["state"] == "uncached": raise IndexFailure("Render this collection before indexing it.")
    if state["indexed"] and not force:
        logger.info("Index cache hit file=%s", index_path(csv_path, directory))
        return state
    started, path, temp = time.perf_counter(), index_path(csv_path, directory), None
    logger.info("Index build started source=%s force=%s", csv_path, force)
    try:
        source_hash = fingerprint(csv_path)
        papers = load_papers_csv(csv_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        handle, name = tempfile.mkstemp(prefix=path.stem + ".", suffix=".tmp", dir=path.parent)
        os.close(handle)
        temp = Path(name)
        with closing(sqlite3.connect(temp)) as db:
            _create_tokens(db)
            db.executescript("CREATE TABLE documents (doc INTEGER PRIMARY KEY, data TEXT NOT NULL); CREATE TABLE terms (term TEXT PRIMARY KEY, idf REAL NOT NULL) WITHOUT ROWID; CREATE TABLE postings (term TEXT NOT NULL, doc INTEGER NOT NULL, weight REAL NOT NULL, PRIMARY KEY(term,doc)) WITHOUT ROWID; CREATE TABLE metadata (key TEXT PRIMARY KEY, value TEXT NOT NULL);")
            for number, paper in enumerate(papers, 1):
                text = normalize(paper.get("title", "") + " " + paper.get("abstract", ""))
                db.execute("INSERT INTO corpus(rowid,text) VALUES (?,?)", (number, text))
                db.execute("INSERT INTO documents VALUES (?,?)", (number, json.dumps(paper, ensure_ascii=False)))
                if number % 500 == 0: logger.info("Index preprocessing progress papers=%d total=%d", number, len(papers))
            idfs = {term: math.log((1 + len(papers)) / (1 + df)) + 1 for term, df in db.execute("SELECT term,doc FROM vocabulary")}
            db.executemany("INSERT INTO terms VALUES (?,?)", idfs.items())
            db.execute("CREATE VIRTUAL TABLE instances USING fts5vocab(corpus, 'instance')")
            frequencies = db.execute("SELECT doc,term,COUNT(*) FROM instances GROUP BY doc,term ORDER BY doc")
            for doc, group in itertools.groupby(frequencies, key=lambda row: row[0]):
                weights = [(term, (1 + math.log(count)) * idfs[term]) for _, term, count in group]
                norm = math.sqrt(sum(weight * weight for _, weight in weights))
                db.executemany("INSERT INTO postings VALUES (?,?,?)", ((term, doc, weight / norm) for term, weight in weights))
            meta = {"schema": SCHEMA, "normalization": VERSION, "source": csv_path.name, "source_sha256": source_hash, "count": len(papers), "terms": len(idfs), "updated_at": datetime.now(timezone.utc).isoformat()}
            db.execute("INSERT INTO metadata VALUES ('index',?)", (json.dumps(meta),))
            db.execute("DROP TABLE instances")
            db.execute("DROP TABLE vocabulary")
            db.execute("DROP TABLE corpus")
            db.commit()
            db.execute("VACUUM")
        if fingerprint(csv_path) != source_hash: raise IndexFailure("The CSV changed while indexing. Reindex to use the latest papers.")
        os.replace(temp, path)
        logger.info("Index build completed papers=%d terms=%d file=%s duration_ms=%.1f", len(papers), len(idfs), path, (time.perf_counter() - started) * 1000)
        return index_status(csv_path, directory)
    except (OSError, sqlite3.Error, ValueError, KeyError, TypeError) as exc:
        logger.exception("Index build failed source=%s; previous index preserved", csv_path)
        raise IndexFailure("Indexing failed. Check the server logs and try Reindex.") from exc
    finally:
        if temp and temp.exists(): temp.unlink()
def _query_counts(query):
    with closing(sqlite3.connect(":memory:")) as db:
        _create_tokens(db)
        db.execute("INSERT INTO corpus(text) VALUES (?)", (normalize(query),))
        return dict(db.execute("SELECT term,cnt FROM vocabulary"))
def search(csv_path, directory, query, k=10):
    if not 1 <= k <= 100: raise ValueError("Top k must be between 1 and 100.")
    if not query.strip() or len(query) > 1000: raise ValueError("Enter a query between 1 and 1000 characters.")
    state = index_status(csv_path, directory)
    if not state["indexed"]: raise IndexFailure("This collection needs indexing or reindexing before it can be searched.")
    started, counts = time.perf_counter(), _query_counts(query)
    if not counts: return []
    path = index_path(csv_path, directory)
    try:
        with closing(_connect(path)) as db:
            placeholders = ",".join("?" for _ in counts)
            weights = [(term, (1 + math.log(counts[term])) * idf) for term, idf in db.execute(f"SELECT term,idf FROM terms WHERE term IN ({placeholders})", tuple(counts))]
            norm = math.sqrt(sum(weight * weight for _, weight in weights))
            if not norm: return []
            values = ",".join("(?,?)" for _ in weights)
            params = [item for term, weight in weights for item in (term, weight / norm)]
            matches = db.execute(f"WITH query(term,weight) AS (VALUES {values}), ranked AS (SELECT p.doc,SUM(p.weight*q.weight) AS score FROM postings p JOIN query q ON p.term=q.term GROUP BY p.doc ORDER BY score DESC,p.doc LIMIT ?) SELECT d.data,r.score FROM ranked r JOIN documents d ON d.doc=r.doc ORDER BY r.score DESC,r.doc", params + [k])
            results = [{**json.loads(data), "score": min(1.0, max(0.0, score))} for data, score in matches]
        logger.info("Search completed collection=%s query_terms=%d top_k=%d returned=%d duration_ms=%.1f", Path(csv_path).name, len(counts), k, len(results), (time.perf_counter() - started) * 1000)
        return results
    except (OSError, sqlite3.Error, ValueError, TypeError) as exc:
        logger.exception("Search failed index=%s", path)
        raise IndexFailure("The index could not be searched. Reindex this collection.") from exc
