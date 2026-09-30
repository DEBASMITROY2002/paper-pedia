"""Persistent per-collection TF-IDF indexes and cosine-similarity search."""
from .tfidf import build_index, index_status, search, IndexFailure
