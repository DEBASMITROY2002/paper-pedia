import html, logging, os, re, threading, unicodedata
from functools import lru_cache
from pathlib import Path
from bs4 import BeautifulSoup
from .tfidf import IndexFailure
logger = logging.getLogger(__name__)
MODEL = "openai/clip-vit-base-patch32"
REVISION = "3d74acf9a28c67741b2f4f2ea7635f0aaf6f0268"
VERSION = "clip-full-text-chunks-v1"
def clean_text(text):
    text = html.unescape(str(text or ""))
    if re.search(r"</?(?:p|div|span|a|br|b|i|em|strong|script|style)\b", text, re.I):
        soup = BeautifulSoup(text, "html.parser")
        for tag in soup(["script", "style"]): tag.decompose()
        text = soup.get_text(" ")
    return " ".join(unicodedata.normalize("NFKC", text).split())
def select_device(torch):
    requested = os.environ.get("PAPER_PEDIA_CLIP_DEVICE", "auto").lower()
    mps = hasattr(torch.backends, "mps") and torch.backends.mps.is_available()
    cuda = torch.cuda.is_available()
    available = {"cpu": True, "mps": mps, "cuda": cuda}
    if requested != "auto":
        if not available.get(requested): raise IndexFailure(f"Requested CLIP device {requested!r} is unavailable.")
        return requested
    return "mps" if mps else "cuda" if cuda else "cpu"
class ClipEncoder:
    def __init__(self, cache_dir):
        try:
            import torch
            from transformers import CLIPTextModelWithProjection, CLIPTokenizerFast
        except ImportError as exc: raise IndexFailure("Install the project dependencies to enable CLIP (torch, transformers, numpy).") from exc
        self.torch, self.lock = torch, threading.RLock()
        self.device = select_device(torch)
        cache_dir = Path(cache_dir)
        local = cache_dir / "text"
        logger.info("Loading CLIP model=%s device=%s cache=%s", MODEL, self.device, cache_dir)
        try:
            if (local / "model.safetensors").exists():
                self.tokenizer = CLIPTokenizerFast.from_pretrained(local, local_files_only=True)
                self.model = CLIPTextModelWithProjection.from_pretrained(local, local_files_only=True, use_safetensors=True)
            else:
                logger.info("Downloading CLIP model on first use; this may take several minutes")
                self.tokenizer = CLIPTokenizerFast.from_pretrained(MODEL, revision=REVISION, cache_dir=cache_dir / "downloads")
                self.model = CLIPTextModelWithProjection.from_pretrained(MODEL, revision=REVISION, cache_dir=cache_dir / "downloads", use_safetensors=False, weights_only=True)
                self.model.save_pretrained(local, safe_serialization=True)
                self.tokenizer.save_pretrained(local)
            self.model.eval()
            try: self.model.to(self.device)
            except RuntimeError:
                if self.device == "cpu": raise
                logger.warning("CLIP device initialization failed; falling back to CPU", exc_info=True)
                self.device = "cpu"
                self.model.to("cpu")
            self.dimension = self.model.config.projection_dim
            self.context = self.model.config.max_position_embeddings
            self.batch_size = max(1, min(256, int(os.environ.get("PAPER_PEDIA_CLIP_BATCH_SIZE", "32"))))
            logger.info("CLIP ready device=%s dimensions=%d batch_size=%d", self.device, self.dimension, self.batch_size)
        except Exception as exc:
            logger.exception("CLIP model initialization failed")
            raise IndexFailure("CLIP could not load. Check server logs and internet access for the first model download.") from exc
    def _chunks(self, texts):
        capacity = self.context - 2
        for owner, text in enumerate(texts):
            ids = self.tokenizer(clean_text(text), add_special_tokens=False, truncation=False, verbose=False)["input_ids"]
            for offset in range(0, max(len(ids), 1), capacity):
                piece = ids[offset:offset + capacity]
                yield owner, max(len(piece), 1), [self.tokenizer.bos_token_id] + piece + [self.tokenizer.eos_token_id]
    def _encode(self, texts):
        import itertools, numpy as np
        torch = self.torch
        vectors = np.zeros((len(texts), self.dimension), dtype=np.float32)
        chunks, processed = iter(self._chunks(texts)), 0
        with torch.inference_mode():
            while batch := list(itertools.islice(chunks, self.batch_size)):
                inputs = self.tokenizer.pad({"input_ids": [row[2] for row in batch]}, padding="max_length", max_length=self.context, return_tensors="pt")
                inputs = {key: value.to(self.device) for key, value in inputs.items()}
                features = self.model(**inputs).text_embeds.float()
                features = torch.nn.functional.normalize(features, dim=-1).cpu().numpy()
                for (owner, length, _), vector in zip(batch, features): vectors[owner] += vector * length
                processed += len(batch)
                if processed % (self.batch_size * 16) == 0:
                    logger.info("CLIP encoding progress chunks=%d papers_reached=%d total_papers=%d device=%s", processed, batch[-1][0] + 1, len(texts), self.device)
        norms = np.linalg.norm(vectors, axis=1, keepdims=True)
        if not np.isfinite(vectors).all() or np.any(norms == 0): raise IndexFailure("CLIP produced invalid embeddings; previous index preserved.")
        return vectors / norms
    def encode(self, texts):
        with self.lock:
            try: return self._encode(texts)
            except RuntimeError:
                if self.device == "cpu": raise
                logger.warning("CLIP acceleration failed; retrying on CPU", exc_info=True)
                self.device = "cpu"
                self.model.to("cpu")
                return self._encode(texts)
    def scores(self, matrix, query):
        with self.lock, self.torch.inference_mode():
            try:
                docs = self.torch.from_numpy(matrix).to(self.device)
                needle = self.torch.from_numpy(query).to(self.device)
                return (docs @ needle).cpu().numpy()
            except RuntimeError:
                logger.warning("CLIP vector scoring falling back to CPU", exc_info=True)
                return matrix @ query
@lru_cache(maxsize=1)
def get_encoder(cache_dir): return ClipEncoder(cache_dir)
