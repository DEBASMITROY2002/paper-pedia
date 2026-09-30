<p align="center">
  <img src="src/paper_pedia/server/static/logo.png" width="120" alt="Paper Pedia logo">
</p>
<h1 align="center">Paper Pedia</h1>
<p align="center"><strong>Turn conference proceedings into a searchable research library.</strong></p>
<p align="center">Browse a venue. Save a collection. Find the papers worth reading next.</p>
<p align="center">
  <img src="https://img.shields.io/badge/Python-3.12%2B-3776AB?logo=python&logoColor=white" alt="Python 3.12 or newer">
  <img src="https://img.shields.io/badge/FastAPI-server--rendered-009688?logo=fastapi&logoColor=white" alt="Built with FastAPI">
  <img src="https://img.shields.io/badge/Search-CLIP%20%7C%20TF--IDF%20%7C%20Jaccard-176c58" alt="Three search methods">
  <a href="LICENSE"><img src="https://img.shields.io/badge/License-Apache%202.0-blue" alt="Apache 2.0 license"></a>
</p>
<p align="center">
  <a href="#why-paper-pedia">Why Paper Pedia?</a> ·
  <a href="#quick-start">Quick start</a> ·
  <a href="#three-ways-to-find-a-paper">Search methods</a> ·
  <a href="#your-data-your-files">Your data</a>
</p>

## Why Paper Pedia?

A conference publishes thousands of papers. You have a research question, a few keywords, and limited time to work through them.

Paper Pedia helps you turn that long list into a focused reading shortlist. Pick a **venue, year, and section**—for example, CVPR 2026 Oral—save its paper metadata locally, and search the collection using the method that fits your question.

It is useful when you want to:

- **Start a literature review.** Search a specific conference edition instead of sorting through unrelated years and venues.
- **Catch up on a research area.** Explore collections from ICLR, CVPR, NeurIPS, ACL, and other venues discovered through Papers Cool.
- **Find familiar terminology or explore a topic.** Switch between keyword relevance, dense text embeddings, and normalized word overlap.
- **Return to the same collection without fetching it again.** Reuse local paper caches and search indexes across server restarts.
- **Take the results into your own workflow.** Download CSVs for notebooks, analysis, reading lists, or another application.

Search runs on your machine. Once a collection and its required index/model are cached, searching that collection does not require a hosted inference service or an API key.

## A small workflow with a useful payoff

**Browse → Render → Index → Search → Read**

1. **Expand a venue.** The home page lists available years and sections in collapsed venue cards.
2. **Render a collection.** Paper Pedia loads its existing CSV or fetches the paper metadata and saves it locally.
3. **Choose an index.** Build **TF-IDF** for Sparse and Subset search, or **CLIP** for Dense search.
4. **Ask your question.** Select a search method, enter a query, and choose how many results to return.
5. **Explore the shortlist.** Read titles, authors, and abstracts; follow the original paper or PDF links.

For example, select **CVPR → 2026 → Oral**, build an index, and try:

> reconstructing a 3D scene from a single image

Choose **Dense (CLIP)** to rank by embedding similarity, **Sparse (TF-IDF)** for distinctive terms, or **Subset (Jaccard)** for word-set overlap. Each search stays within the selected collection.

## Three ways to find a paper

### 🧠 Dense · CLIP

Encodes titles and abstracts with the text encoder from [`openai/clip-vit-base-patch32`](https://huggingface.co/openai/clip-vit-base-patch32), then ranks papers by cosine similarity to the query.

- Uses **MPS on supported Macs**, otherwise CUDA when available, then CPU.
- Processes long text in chunks and combines their embeddings, so an abstract is not silently cut off at CLIP's token limit.
- Caches the model locally after its initial download.
- Has its own **Index CLIP / Reindex CLIP** controls and index files.

Try it when you can describe what you are looking for but do not have an exact title or phrase. CLIP was trained for image–text alignment; its relevance for specialized research terminology can vary. The other search methods provide useful alternatives.

### 🔎 Sparse · TF-IDF

Ranks papers by distinctive terms shared with your query, using normalized TF-IDF vectors and cosine similarity.

- Searches **title + abstract**.
- Cleans HTML, normalizes Unicode and case, removes English stop words, and applies English stemming.
- Stores sparse term postings in SQLite.
- Requires no model download.

Try it for named methods, technical vocabulary, or a handful of precise keywords.

### 🧩 Subset · Jaccard

Compares the unique normalized words in the query and each paper:

```text
Jaccard similarity = shared words / all distinct words in either text
```

It reuses the TF-IDF index's normalized token sets. Repeating a word does not increase the score, and query words absent from the collection still count toward the union.

Try it when you want an overlap-based comparison. “Subset” is the UI label; scoring uses Jaccard similarity, not a strict subset test.

> Choose **Top k** from 1 to 100. Scores are similarity measures, not probabilities, and should not be compared directly across methods. Sparse and Jaccard search return fewer than k results when fewer papers have a positive match.

## Quick start

Requires **Python 3.12+**. The recommended setup uses [uv](https://docs.astral.sh/uv/).

```bash
git clone https://github.com/DEBASMITROY2002/paper-pedia.git
cd paper-pedia
uv sync
uv run uvicorn wsgi:app --app-dir src --reload
```

Open **[http://127.0.0.1:8000](http://127.0.0.1:8000)**.

On a fresh installation, the app fetches the venue catalog when needed. Rendering uncached papers needs internet access. The first CLIP indexing operation also downloads model weights; subsequent operations use the local cache.

<details>
<summary><strong>Prefer pip?</strong></summary>

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -e .
python -m uvicorn wsgi:app --app-dir src --reload
```

On Windows, activate the environment with `.venv\Scripts\activate` instead.

</details>

## Built for collections you come back to

- **Visible cache and index status.** See which collections are ready to open or search.
- **Separate refresh controls.** Refresh the venue catalog, a collection's papers, or either search index independently.
- **Search readiness checks.** Search is disabled with **“Not yet indexed”** when the chosen collection and method lack an index. A changed CSV requires reindexing.
- **Progress checkpoints.** Every 500 unique papers, the scraper saves a cumulative `.partial.csv` checkpoint.
- **Safe replacements.** Failed downloads and failed index builds preserve the previous complete files.
- **Duplicate handling.** Duplicate paper entries are removed; stalled pagination still stops instead of silently accepting an incomplete collection.
- **Useful backend logs.** Follow cache hits, fetching progress, indexing, device selection, request timings, and errors.

The scraper requests up to 10,000 entries at a time and continues paging if the source limits the response or more entries remain. A completed render shows a popup with the number of papers loaded.

## Your data, your files

The default data directory is `src/data`, independent of the directory from which you start the server.

```text
src/data/
├── catalog.json
├── venues/
│   ├── CVPR.2026__Oral.csv
│   └── <collection>.partial.csv          # Present during an unfinished scrape
├── indices/
│   └── CVPR.2026__Oral.tfidf.sqlite3      # TF-IDF and Jaccard
├── clip_indices/
│   └── CVPR.2026__Oral.clip.sqlite3       # CLIP embeddings
├── models/
│   └── clip/                            # Downloaded model and local text encoder
└── logs/
    └── paper-pedia.log
```

Each index keeps its corresponding CSV's filename prefix. Source fingerprints identify changed collections so an old index cannot silently search a newer CSV.

CSVs include paper IDs, titles, authors, abstracts, keywords, venue details, source links, PDF links, and scrape timestamps. List-valued fields such as authors are stored as JSON arrays inside CSV cells.

**A checkpoint is not a finished collection.** It is retained if a download fails, but the next retry starts a fresh scrape. Partial CSVs are not indexed. After a successful download, the complete CSV replaces the old cache and the checkpoint is removed.

## Use it from a script

Interactive API documentation is available at **[http://127.0.0.1:8000/docs](http://127.0.0.1:8000/docs)**.

<details>
<summary><strong>Example: render, index, and search a collection</strong></summary>

```bash
# Fetch or reuse the collection's paper CSV.
curl --get http://127.0.0.1:8000/api/venues/papers \
  --data-urlencode 'venue=CVPR' \
  --data-urlencode 'year=2026' \
  --data-urlencode 'group=Oral'

# Build the shared TF-IDF / Jaccard index.
curl -X POST \
  'http://127.0.0.1:8000/api/venues/index?venue=CVPR&year=2026&group=Oral'

# Find the top 10 keyword matches.
curl --get http://127.0.0.1:8000/api/venues/search \
  --data-urlencode 'venue=CVPR' \
  --data-urlencode 'year=2026' \
  --data-urlencode 'group=Oral' \
  --data-urlencode 'q=3D scene reconstruction' \
  --data-urlencode 'mode=sparse' \
  --data-urlencode 'k=10'
```

Use `mode=subset` for Jaccard. For Dense search, first POST to `/api/venues/clip-index` with the same collection parameters, then search with `mode=dense`. Add `force=true` to an indexing request to rebuild it.

</details>

<details>
<summary><strong>Command-line scraping</strong></summary>

```bash
uv run paper-pedia catalog
uv run paper-pedia scrape --venue CVPR.2026 --group Oral
uv run paper-pedia scrape --venue ICLR.2024 --group Spotlight --refresh
```

Omit `--group` to fetch all papers in a venue edition.

</details>

## Configuration

Optional environment variables:

- `PAPER_PEDIA_DATA_DIR`: choose a different data directory; an absolute path is recommended.
- `PAPER_PEDIA_LOG_LEVEL`: `DEBUG`, `INFO`, `WARNING`, `ERROR`, or `CRITICAL`; defaults to `INFO`.
- `PAPER_PEDIA_CLIP_DEVICE`: `auto`, `mps`, `cuda`, or `cpu`; defaults to `auto`.
- `PAPER_PEDIA_CLIP_BATCH_SIZE`: embedding chunk batch size; defaults to `32`.

For example, to force CPU inference:

```bash
PAPER_PEDIA_CLIP_DEVICE=cpu uv run uvicorn wsgi:app --app-dir src --reload
```

Logs are written to the terminal and `logs/paper-pedia.log` inside the configured data directory. The file rotates at 5 MB and retains up to three backups. Requests receive an `X-Request-ID` to help trace related log entries.

## A few practical notes

- **Paper Pedia indexes metadata, not full PDFs.** PDF buttons link to external sources; PDF contents are not downloaded or searched.
- **Caches do not expire automatically.** Use Refresh when you want newer data, then rebuild any stale indexes.
- **Fetching and indexing are synchronous.** Large collections may take time; watch the backend logs for progress.
- **Sparse indexing requires SQLite FTS5.** It is included in the Python environment used to develop this project.
- **The app is intended for local, single-user use.** Add authentication and deployment controls before exposing it publicly.
- Despite its filename, `src/wsgi.py` exports an **ASGI** app. Run it with Uvicorn.

## Project layout

```text
src/
├── wsgi.py                  # Server entry point
├── data/                    # Local collections, indexes, models, and logs
└── paper_pedia/
    ├── cli.py               # Catalog and scraping commands
    ├── scraper/             # Papers Cool discovery and pagination
    ├── storage/             # CSV persistence and atomic writes
    ├── index/               # TF-IDF, CLIP, preprocessing, and Jaccard
    └── server/
        ├── apis/            # JSON and CSV endpoints
        ├── pages/           # Server-rendered page routes
        ├── templates/       # Jinja templates
        └── static/          # Styles, browser interactions, and logo
```

## Contributing

Ideas, bug reports, and improvements are welcome. Useful areas to explore include additional paper sources, retrieval-quality evaluation, background indexing, and reading-list workflows.

If a collection fails to render, include the venue, year, section, and relevant request ID or log excerpt in an [issue](https://github.com/DEBASMITROY2002/paper-pedia/issues). For a search issue, include the selected method and a small example query.

## Acknowledgments and license

Paper metadata is discovered through [Papers Cool](https://papers.cool/). Dense search uses [OpenAI's CLIP model](https://huggingface.co/openai/clip-vit-base-patch32), loaded locally through Transformers and PyTorch.

Paper Pedia's code is licensed under [Apache 2.0](LICENSE). Papers, metadata sources, artwork, and model weights remain subject to their respective licenses and terms.
