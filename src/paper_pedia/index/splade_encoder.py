import html, logging, os, re, threading, unicodedata
from functools import lru_cache
from pathlib import Path
from bs4 import BeautifulSoup
from .tfidf import IndexFailure
logger = logging.getLogger(__name__)
MODEL = "naver/splade-cocondenser-ensembledistil"
REVISION = "49cf4c7b0db5b870a401ddf5e2669993ef3699c7"
VERSION = "splade-log1p-relu-max-full-text-v1"
def clean_text(text):
    text = html.unescape(str(text or ""))
    if re.search(r"</?(?:p|div|span|a|br|b|i|em|strong|script|style)\b", text, re.I):
        soup = BeautifulSoup(text, "html.parser")
        for tag in soup(["script", "style"]): tag.decompose()
        text = soup.get_text(" ")
    return " ".join(unicodedata.normalize("NFKC", text).split())
def select_device(torch):
    requested = os.environ.get("PAPER_PEDIA_SPLADE_DEVICE", "auto").lower()
    mps = hasattr(torch.backends, "mps") and torch.backends.mps.is_available()
    cuda = torch.cuda.is_available()
    available = {"cpu": True, "mps": mps, "cuda": cuda}
    if requested != "auto":
        if not available.get(requested): raise IndexFailure(f"Requested SPLADE device {requested!r} is unavailable.")
        return requested
    return "mps" if mps else "cuda" if cuda else "cpu"
def splade_pool(logits, attention_mask):
    # Canonical SPLADE activation and max pooling; padding contributes zero.
    activations = logits.float().relu_().log1p_()
    activations.mul_(attention_mask.unsqueeze(-1))
    return activations.amax(dim=1)
class SpladeEncoder:
    def __init__(self, cache_dir):
        try:
            import torch
            from transformers import AutoModelForMaskedLM, AutoTokenizer
        except ImportError as exc: raise IndexFailure("Install the project dependencies to enable SPLADE (torch, transformers, numpy).") from exc
        self.torch, self.lock = torch, threading.RLock()
        self.device = select_device(torch)
        cache_dir, local = Path(cache_dir), Path(cache_dir) / REVISION
        logger.info("Loading SPLADE model=%s device=%s cache=%s", MODEL, self.device, cache_dir)
        try:
            if (local / "model.safetensors").exists():
                self.tokenizer = AutoTokenizer.from_pretrained(local, local_files_only=True)
                self.model = AutoModelForMaskedLM.from_pretrained(local, local_files_only=True, use_safetensors=True)
            else:
                logger.info("Downloading SPLADE model on first use; this may take several minutes")
                self.tokenizer = AutoTokenizer.from_pretrained(MODEL, revision=REVISION, cache_dir=cache_dir / "downloads")
                self.model = AutoModelForMaskedLM.from_pretrained(MODEL, revision=REVISION, cache_dir=cache_dir / "downloads", use_safetensors=False, weights_only=True)
                self.model.save_pretrained(local, safe_serialization=True)
                self.tokenizer.save_pretrained(local)
            self.model.eval()
            try: self.model.to(self.device)
            except RuntimeError:
                if self.device == "cpu": raise
                logger.warning("SPLADE device initialization failed; falling back to CPU", exc_info=True)
                self.device = "cpu"
                self.model.to("cpu")
            self.dimension = self.model.config.vocab_size
            self.context = self.model.config.max_position_embeddings
            self.batch_size = max(1, min(16, int(os.environ.get("PAPER_PEDIA_SPLADE_BATCH_SIZE", "2"))))
            logger.info("SPLADE ready device=%s vocabulary=%d batch_size=%d", self.device, self.dimension, self.batch_size)
        except Exception as exc:
            logger.exception("SPLADE model initialization failed")
            raise IndexFailure("SPLADE could not load. Check server logs and internet access for the first model download.") from exc
    def _chunks(self, texts):
        capacity = self.context - self.tokenizer.num_special_tokens_to_add(pair=False)
        for owner, text in enumerate(texts):
            text = clean_text(text)
            if not text: continue
            ids = self.tokenizer(text, add_special_tokens=False, truncation=False, verbose=False)["input_ids"]
            for offset in range(0, len(ids), capacity):
                yield owner, self.tokenizer.build_inputs_with_special_tokens(ids[offset:offset + capacity])
    def _encode(self, texts):
        import itertools, numpy as np
        vectors = [{} for _ in texts]
        chunks, processed = iter(self._chunks(texts)), 0
        with self.torch.inference_mode():
            while batch := list(itertools.islice(chunks, self.batch_size)):
                inputs = self.tokenizer.pad({"input_ids": [row[1] for row in batch]}, padding=True, return_attention_mask=True, return_tensors="pt")
                inputs = {key: value.to(self.device) for key, value in inputs.items()}
                logits = self.model(**inputs).logits
                pooled = splade_pool(logits, inputs["attention_mask"]).cpu().numpy()
                if not np.isfinite(pooled).all(): raise IndexFailure("SPLADE produced invalid weights; previous index preserved.")
                for (owner, _), row in zip(batch, pooled):
                    for term in np.flatnonzero(row > 0):
                        value = float(row[term])
                        vectors[owner][int(term)] = max(vectors[owner].get(int(term), 0.0), value)
                processed += len(batch)
                if processed % (self.batch_size * 32) == 0:
                    logger.info("SPLADE encoding progress chunks=%d papers_reached=%d total_papers=%d device=%s", processed, batch[-1][0] + 1, len(texts), self.device)
        return vectors
    def encode(self, texts):
        with self.lock:
            try: return self._encode(texts)
            except RuntimeError:
                if self.device == "cpu": raise
                logger.warning("SPLADE acceleration failed; retrying on CPU", exc_info=True)
                self.device = "cpu"
                self.model.to("cpu")
                return self._encode(texts)
_load_lock = threading.RLock()
@lru_cache(maxsize=1)
def _cached_encoder(cache_dir): return SpladeEncoder(cache_dir)
def get_encoder(cache_dir):
    with _load_lock: return _cached_encoder(cache_dir)
