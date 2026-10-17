"""RAG service — FastAPI, CPU multilingual embedder + FAISS index.

Endpointy:
  GET  /health
  POST /rag/index   {"paths": ["/.../subor.pdf", ...]}   → naindexuje PDF/TXT
  GET  /rag/search?q=...&k=5                              → top-k chunkov
  GET  /rag/stats

Embedder default = BAAI/bge-m3 (silný multilingválny, dobrý pre slovenčinu). Beží na CPU.
Index sa perzistuje do INDEX_DIR (FAISS + metadáta), aby sa po reštarte nemuselo reindexovať.

Env:
  RAG_EMBED_MODEL   (default BAAI/bge-m3)
  RAG_INDEX_DIR     (default ./rag_index)
  RAG_DEVICE        (default cpu)
  RAG_CHUNK_CHARS   (default 700)  RAG_CHUNK_OVERLAP (default 120)
  OMP_NUM_THREADS   nastav na počet jadier pre embedder (napr. 32)
"""
from __future__ import annotations

import os
import re
import json
import glob
import logging
import threading
from pathlib import Path
from typing import List, Dict

import numpy as np
from fastapi import FastAPI, Body
import uvicorn

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(message)s")
log = logging.getLogger("rag")

EMBED_MODEL = os.environ.get("RAG_EMBED_MODEL", "BAAI/bge-m3")
INDEX_DIR = Path(os.environ.get("RAG_INDEX_DIR", "./rag_index"))
DEVICE = os.environ.get("RAG_DEVICE", "cpu")
CHUNK_CHARS = int(os.environ.get("RAG_CHUNK_CHARS", "700"))
CHUNK_OVERLAP = int(os.environ.get("RAG_CHUNK_OVERLAP", "120"))

_model = None
_index = None
_meta: List[Dict] = []      # paralelné s vektormi v indexe: {text, source, chunk_id}
_dim = None
_lock = threading.Lock()
_bm25 = None                # sparse zložka hybridu (exact-match: verše, mená, citáty)
RRF_K = 60                  # reciprocal rank fusion konštanta
TOP_N = 30                  # koľko kandidátov z každej zložky pred fúziou


def _tok(text: str) -> List[str]:
    """Tokenizácia pre BM25 — lowercase + hrubý prefixový stemming pre slovenskú
    flektívnosť (hrdzavá/hrdzavú/hrdzavého → hrdzav). Dlhé slová sa krátia na 6 znakov;
    rovnaká transformácia na indexe aj dopyte, takže pádové tvary sa spárujú."""
    return [w if len(w) <= 6 else w[:6]
            for w in re.findall(r"\w+", text.lower(), re.UNICODE)]


def _build_bm25():
    global _bm25
    if not _meta:
        _bm25 = None
        return
    from rank_bm25 import BM25Okapi
    _bm25 = BM25Okapi([_tok(m["text"]) for m in _meta])
    log.info("BM25 postavený nad %d chunkmi", len(_meta))


# ---------- načítanie modelu ----------
def get_model():
    global _model, _dim
    if _model is None:
        from sentence_transformers import SentenceTransformer
        log.info("Načítavam embedder %s na %s ...", EMBED_MODEL, DEVICE)
        _model = SentenceTransformer(EMBED_MODEL, device=DEVICE)
        _dim = _model.get_sentence_embedding_dimension()
        log.info("Embedder OK, dim=%d", _dim)
    return _model


def embed(texts: List[str], is_query: bool = False) -> np.ndarray:
    m = get_model()
    # bge-m3 a e5 ťažia z prefixov; pre bge-m3 nie sú nutné, pre e5 áno
    if "e5" in EMBED_MODEL.lower():
        texts = [("query: " if is_query else "passage: ") + t for t in texts]
    vecs = m.encode(texts, normalize_embeddings=True, batch_size=32,
                    show_progress_bar=False, convert_to_numpy=True)
    return vecs.astype("float32")


# ---------- FAISS ----------
def _new_index(dim):
    import faiss
    return faiss.IndexFlatIP(dim)   # kosínus (vektory sú normalizované)


_manifest = ""


def _load_manifest():
    global _manifest
    mp = INDEX_DIR / "manifest.txt"
    _manifest = mp.read_text(encoding="utf-8").strip() if mp.exists() else ""


def _load_index():
    global _index, _meta, _dim
    import faiss
    idx_path = INDEX_DIR / "faiss.index"
    meta_path = INDEX_DIR / "meta.jsonl"
    _load_manifest()
    if idx_path.exists() and meta_path.exists():
        _index = faiss.read_index(str(idx_path))
        _meta = [json.loads(l) for l in open(meta_path, encoding="utf-8")]
        _dim = _index.d
        log.info("Index načítaný: %d chunkov, dim=%d", _index.ntotal, _dim)
        _build_bm25()
    else:
        log.info("Žiadny existujúci index v %s", INDEX_DIR)


def _save_index():
    import faiss
    INDEX_DIR.mkdir(parents=True, exist_ok=True)
    faiss.write_index(_index, str(INDEX_DIR / "faiss.index"))
    with open(INDEX_DIR / "meta.jsonl", "w", encoding="utf-8") as f:
        for m in _meta:
            f.write(json.dumps(m, ensure_ascii=False) + "\n")
    log.info("Index uložený (%d chunkov)", _index.ntotal)


# ---------- text extrakcia + chunking ----------
def read_text(path: str) -> str:
    p = Path(path)
    suf = p.suffix.lower()
    if suf == ".pdf":
        from pypdf import PdfReader
        r = PdfReader(str(p))
        return "\n".join((pg.extract_text() or "") for pg in r.pages)
    if suf == ".rtf":
        from striprtf.striprtf import rtf_to_text
        return rtf_to_text(p.read_text(encoding="utf-8", errors="replace"))
    return p.read_text(encoding="utf-8", errors="replace")


def chunk_text(text: str) -> List[str]:
    # normalizuj whitespace, ale zachovaj odseky (prázdne riadky)
    text = re.sub(r"[ \t]+", " ", text)
    paras = [p.strip() for p in re.split(r"\n\s*\n", text) if p.strip()]
    chunks, buf = [], ""
    for para in paras:
        if len(buf) + len(para) + 1 <= CHUNK_CHARS:
            buf = (buf + "\n" + para).strip()
        else:
            if buf:
                chunks.append(buf)
            # ak je odsek dlhší než chunk, rozseká sa s prekryvom
            if len(para) > CHUNK_CHARS:
                i = 0
                while i < len(para):
                    chunks.append(para[i:i + CHUNK_CHARS])
                    i += CHUNK_CHARS - CHUNK_OVERLAP
                buf = ""
            else:
                buf = para
    if buf:
        chunks.append(buf)
    return chunks


def index_paths(paths: List[str]) -> Dict:
    global _index
    with _lock:
        if _index is None:
            _load_index()
        new_texts, new_meta = [], []
        for path in paths:
            files = glob.glob(path) if any(c in path for c in "*?[") else [path]
            for fp in files:
                try:
                    txt = read_text(fp)
                except Exception as e:
                    log.warning("preskakujem %s: %s", fp, e)
                    continue
                chs = chunk_text(txt)
                for i, ch in enumerate(chs):
                    new_texts.append(ch)
                    new_meta.append({"text": ch, "source": os.path.basename(fp), "chunk_id": i})
                log.info("%s → %d chunkov", os.path.basename(fp), len(chs))
        if not new_texts:
            return {"indexed_chunks": 0, "total": _index.ntotal if _index else 0}
        vecs = embed(new_texts, is_query=False)
        if _index is None:
            _index = _new_index(vecs.shape[1])
        _index.add(vecs)
        _meta.extend(new_meta)
        _save_index()
        _build_bm25()
        return {"indexed_chunks": len(new_texts), "total": _index.ntotal}


def search(q: str, k: int = 5) -> List[Dict]:
    """Hybrid: dense (FAISS) + sparse (BM25), zlúčené cez reciprocal rank fusion.
    Dense chytá parafrázy/význam, BM25 presné slová (verše, citáty, názvy, mená)."""
    if _index is None or _index.ntotal == 0:
        return []
    n = min(TOP_N, _index.ntotal)
    qv = embed([q], is_query=True)
    _, idxs = _index.search(qv, n)
    fused = {int(i): 1.0 / (RRF_K + r + 1)
             for r, i in enumerate(idxs[0]) if i >= 0}
    if _bm25 is not None:
        bs = _bm25.get_scores(_tok(q))
        for r, i in enumerate(np.argsort(bs)[::-1][:n]):
            if bs[i] <= 0:
                break
            fused[int(i)] = fused.get(int(i), 0.0) + 1.0 / (RRF_K + r + 1)
    out = []
    for i, score in sorted(fused.items(), key=lambda x: -x[1])[:k]:
        m = _meta[i]
        out.append({"score": round(float(score), 4), "source": m["source"],
                    "chunk_id": m["chunk_id"], "text": m["text"]})
    return out


# ---------- API ----------
app = FastAPI(title="RAG service")


@app.get("/health")
def health():
    return {"ok": True, "chunks": _index.ntotal if _index else 0, "model": EMBED_MODEL}


@app.get("/rag/manifest")
def manifest():
    return {"manifest": _manifest}


@app.post("/rag/index")
def api_index(payload: dict = Body(...)):
    return index_paths(payload.get("paths", []))


@app.get("/rag/search")
def api_search(q: str, k: int = 5):
    return {"query": q, "results": search(q, k)}


@app.get("/rag/stats")
def stats():
    srcs = {}
    for m in _meta:
        srcs[m["source"]] = srcs.get(m["source"], 0) + 1
    return {"chunks": _index.ntotal if _index else 0, "sources": srcs, "model": EMBED_MODEL}


if __name__ == "__main__":
    _load_index()
    get_model()  # warm
    port = int(os.environ.get("RAG_PORT", "8100"))
    uvicorn.run(app, host="0.0.0.0", port=port, log_level="info")
