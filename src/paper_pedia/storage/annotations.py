import logging, sqlite3
from contextlib import contextmanager
from pathlib import Path
logger = logging.getLogger(__name__)
@contextmanager
def connect(path):
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(path, timeout=15)
    try:
        db.execute('CREATE TABLE IF NOT EXISTS annotations (paper_id TEXT PRIMARY KEY, marked INTEGER NOT NULL CHECK(marked IN (0,1)), comment TEXT NOT NULL) WITHOUT ROWID')
        yield db
    finally: db.close()
def lookup(path, paper_ids):
    ids = list(dict.fromkeys(paper_ids))
    if not ids or not Path(path).exists(): return {}
    with connect(path) as db:
        result = {}
        for start in range(0, len(ids), 500):
            batch = ids[start:start + 500]
            for identity, marked, comment in db.execute('SELECT paper_id,marked,comment FROM annotations WHERE paper_id IN (' + ','.join('?' for _ in batch) + ')', batch):
                result[identity] = {'marked': bool(marked), 'comment': comment}
        return result
def update(path, paper_id, marked=None, comment=None):
    with connect(path) as db:
        try:
            db.execute('BEGIN IMMEDIATE')
            row = db.execute('SELECT marked,comment FROM annotations WHERE paper_id=?', (paper_id,)).fetchone() or (0, '')
            state = {'marked': bool(row[0]) if marked is None else marked, 'comment': row[1] if comment is None else comment}
            if not state['marked'] and not state['comment']:
                db.execute('DELETE FROM annotations WHERE paper_id=?', (paper_id,))
            else:
                db.execute('INSERT INTO annotations VALUES (?,?,?) ON CONFLICT(paper_id) DO UPDATE SET marked=excluded.marked,comment=excluded.comment', (paper_id, int(state['marked']), state['comment']))
            db.commit()
            logger.info('Paper annotation saved paper_id=%r marked=%s comment_length=%d', paper_id, state['marked'], len(state['comment']))
            return state
        except Exception:
            db.rollback()
            raise
