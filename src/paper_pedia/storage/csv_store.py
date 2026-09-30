import csv, json, os, tempfile
from dataclasses import asdict, fields, is_dataclass
from datetime import datetime, timezone
from pathlib import Path
from paper_pedia.scraper.models import Paper
FIELDS = [f.name for f in fields(Paper)] + ["scraped_at"]
ARRAYS = ("authors", "author_links", "keywords")
def atomic_write(path, write):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    name = None
    try:
        with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", newline="", dir=path.parent, delete=False) as f:
            name = f.name
            write(f)
            f.flush()
            os.fsync(f.fileno())
        os.replace(name, path)
    finally:
        if name and Path(name).exists(): Path(name).unlink()
def save_papers_csv(papers, output_path):
    timestamp = datetime.now(timezone.utc).isoformat()
    def write(f):
        writer = csv.DictWriter(f, fieldnames=FIELDS)
        writer.writeheader()
        for paper in papers:
            row = asdict(paper) if is_dataclass(paper) else dict(paper)
            for key in ARRAYS: row[key] = json.dumps(row.get(key, []), ensure_ascii=False)
            row["scraped_at"] = timestamp
            writer.writerow(row)
    atomic_write(output_path, write)
def load_papers_csv(path):
    with Path(path).open(encoding="utf-8", newline="") as f:
        reader = csv.DictReader(f)
        if not reader.fieldnames or not set(FIELDS) <= set(reader.fieldnames):
            raise ValueError("Paper cache has an invalid CSV header.")
        rows = list(reader)
    for row in rows:
        row["index"], row["year"] = int(row["index"]), int(row["year"])
        for key in ARRAYS:
            row[key] = json.loads(row[key] or "[]")
            if not isinstance(row[key], list): raise ValueError("Invalid array in paper cache.")
    return rows
