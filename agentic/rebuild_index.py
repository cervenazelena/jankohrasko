"""Rebuild RAG indexu (v4) — RIEŠI ROTOVANÝ LAYOUT.
Válkovo PDF: strany sú rotované o 270° a sú to DVOJSTRANY (2 knižné strany vedľa
seba, text zvislý). pypdf aj default extrakcia poprehadzujú riadky. Riešenie:
  1. PyMuPDF: súradnice slov → vizuálny priestor cez page.rotation_matrix.
  2. Rozdeliť na stĺpce (knižné strany) podľa medzery vo vizuálnom x.
  3. Každý stĺpec čítať zhora nadol; stĺpce zoradiť podľa čísla knižnej strany.
→ súvislý text v správnom poradí čítania.
Segmentácia po BÁSŇACH: tituly z OBSAHU (TOC), inline match v správnom poradí
(prvý výskyt = titul). Hlavička chunku: „Básnické dielo Miroslava Válka — X (zbierka Y)".

Použitie:
  python rebuild_index.py --dry-run
  python rebuild_index.py
"""
from __future__ import annotations
import os, re, json, glob, hashlib, argparse, unicodedata
from collections import Counter
from pathlib import Path

import sys
import fitz  # PyMuPDF
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from tools import read_file_text   # jednotná extrakcia rtf/docx/doc

RAG_DOCS = os.environ.get("RAG_DOCS", "./rag_docs")
PDF = f"{RAG_DOCS}/Valek_Basnicke_dielo.pdf"
# (podadresár, label pre hlavičku chunku aj manifest)
COLLECTIONS = [
    ("slovnik19", "Slovník diel slovenskej literatúry 19. storočia"),
    ("slovnik20", "Slovník diel slovenskej literatúry 20. storočia"),
    ("sondy19",   "Sondy do slovenskej literatúry 19. storočia"),
    ("sondy20",   "Sondy do slovenskej literatúry 20. storočia"),
]
VALEK_LABEL = "Básnické dielo Miroslava Válka"
OUT_DIR = Path(os.environ.get("RAG_INDEX_DIR_V2", "./rag_index_v2"))
CHUNK_CHARS, CHUNK_OVERLAP = 700, 120
LINE_TOL = 7.0   # vizuálna y-tolerancia pre zoskupenie do riadku

KNOWN_COLLECTIONS = {"dotyky", "príťažlivosť", "nepokoj", "milovanie v husej koži",
                     "slovo", "básne mimo zbierok", "z pozostalosti", "preklady"}


def norm(s: str) -> str:
    return unicodedata.normalize("NFC", s).strip()


# ---------- 1. čítanie strany v správnom poradí (rotácia + stĺpce) ----------
def page_lines(page) -> list[str]:
    M = page.rotation_matrix
    words = page.get_text("words")
    if not words:
        return []
    vw = []
    for w in words:
        cx, cy = (w[0] + w[2]) / 2, (w[1] + w[3]) / 2
        pt = fitz.Point(cx, cy) * M
        vw.append((pt.x, pt.y, w[4]))
    xs = sorted(t[0] for t in vw)
    span = xs[-1] - xs[0] if len(xs) > 1 else 1
    # dvojstrana: gutter je pri vizuálnej stredovej osi. Deľ na osi, ak sú OBE
    # polovice podstatné (každá ≥15 % slov) — inak jednostĺpcová strana.
    mid = xs[0] + span / 2
    left = [t for t in vw if t[0] < mid]
    right = [t for t in vw if t[0] >= mid]
    n = len(vw)
    if min(len(left), len(right)) >= 0.15 * n:
        groups = [left, right]
    else:
        groups = [vw]

    def to_lines(col):
        col = sorted(col, key=lambda t: (t[1], t[0]))
        lines, cur, cy = [], [], None
        for x, y, word in col:
            if cy is None or abs(y - cy) <= LINE_TOL:
                cur.append((x, word))
            else:
                lines.append(" ".join(w for _, w in sorted(cur)))
                cur = [(x, word)]
            cy = y
        if cur:
            lines.append(" ".join(w for _, w in sorted(cur)))
        return lines

    cols = []
    for g in groups:
        lines = to_lines(g)
        # číslo knižnej strany = posledný čisto-číselný riadok v stĺpci
        pg = None
        for ln in lines:
            if re.fullmatch(r"\d{1,4}", ln.strip()):
                pg = int(ln.strip())
        xmin = min((t[0] for t in g), default=0)
        cols.append((pg, xmin, lines))
    cols.sort(key=lambda c: (c[0] if c[0] is not None else 10 ** 6, c[1]))
    out = []
    for _, _, lines in cols:
        out.extend(lines)
    return out


def read_pages(path):
    doc = fitz.open(path)
    return [page_lines(pg) for pg in doc]


# ---------- 2. TOC ----------
_TOC_RE = re.compile(r"^(.{1,90}?)\s*\.{3,}\s*(\d{1,4})\s*$")
EXTRA_TITLES = ["1944"]   # číselný titul, ktorý TOC extrakcia niekedy stráca


def parse_toc(pages) -> list[str]:
    titles = []
    for lines in pages:
        hits = [norm(m.group(1)) for ln in lines if (m := _TOC_RE.match(ln.strip()))]
        if len(hits) >= 5:
            titles.extend(h for h in hits if len(h) >= 2)
    for t in EXTRA_TITLES:
        if t not in titles:
            titles.append(t)
    return titles


# ---------- 3. segmentácia po básňach (inline, správne poradie) ----------
def is_toc_page(lines) -> bool:
    return sum(1 for ln in lines if _TOC_RE.match(ln.strip())) >= 5


def _ws(s: str) -> str:
    return re.sub(r"\s+", " ", s).strip()


def segment(pages, titles):
    title_set = {_ws(t) for t in titles}
    unused = set(title_set)
    segs = [{"title": "Úvod", "coll": "", "lines": []}]
    coll = ""
    for lines in pages:
        if is_toc_page(lines):
            continue
        prev = None
        for raw in lines:
            s = _ws(norm(raw))
            low = s.lower()
            two = _ws(f"{prev} {s}") if prev else None          # viacriadkový titul
            if low in KNOWN_COLLECTIONS and s.upper() == s:     # CAPS zbierka v tele
                coll = s.capitalize()
                segs.append({"title": coll, "coll": "", "lines": []})
                unused.discard(s)
                prev = s
                continue
            hit = s if s in unused else (two if two in unused else None)
            if hit:                                             # prvý výskyt titulu
                unused.discard(hit)
                if hit == two and segs[-1]["lines"] and _ws(norm(segs[-1]["lines"][-1])) == prev:
                    segs[-1]["lines"].pop()                     # odober prvú časť titulu z tela
                segs.append({"title": hit, "coll": coll, "lines": []})
                prev = s
                continue
            if re.fullmatch(r"\d{1,4}", s):                     # číslo strany
                prev = s
                continue
            segs[-1]["lines"].append(raw)
            prev = s
    matched = len(title_set) - len(unused)
    print(f"[segment] titulov: {len(title_set)} | zhodených: {matched} | segmentov: {len(segs)}")
    real_unmatched = [t for t in unused if not t.startswith(("„", "\""))]
    print("[nezhodené ne-citátové, prvých 25]:", " | ".join(sorted(real_unmatched)[:25]))
    return segs


# ---------- 4. chunking ----------
def chunk_text(text: str) -> list[str]:
    text = re.sub(r"[ \t]+", " ", text)
    paras = [p.strip() for p in re.split(r"\n\s*\n", text) if p.strip()]
    chunks, buf = [], ""
    for para in paras:
        if len(buf) + len(para) + 1 <= CHUNK_CHARS:
            buf = (buf + "\n" + para).strip()
        else:
            if buf:
                chunks.append(buf)
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


def valek_chunks() -> list[dict]:
    if not os.path.exists(PDF):
        print(f"[valek] {PDF} neexistuje — preskakujem")
        return []
    pages = read_pages(PDF)
    titles = parse_toc(pages)
    print(f"[toc] titulov: {len(titles)}")
    segs = segment(pages, titles)
    seen, out, dedup = set(), [], 0
    for sg in segs:
        body = "\n".join(sg["lines"]).strip()
        if len(body) < 20:
            continue
        h = hashlib.md5(re.sub(r"\s+", " ", body).lower().encode()).hexdigest()
        if h in seen:
            dedup += 1
            continue
        seen.add(h)
        head = f"{VALEK_LABEL} — {sg['title']}"
        if sg["coll"]:
            head += f" (zbierka {sg['coll']})"
        for i, ch in enumerate(chunk_text(body)):
            out.append({"text": head + "\n" + ch, "source": "Valek_Basnicke_dielo.pdf",
                        "chunk_id": i, "collection": VALEK_LABEL})
    print(f"[valek] dedup: {dedup} | chunkov: {len(out)}")
    return out


def collection_chunks(dirname: str, label: str) -> list[dict]:
    """Naindexuje jednu kolekciu (adresár rtf/docx/doc). Prvý riadok súboru = názov
    článku → hlavička „<label> — <názov>". Nezávislé od formátu (read_file_text)."""
    out, files = [], []
    for ext in ("*.rtf", "*.docx", "*.doc", "*.txt"):
        files += glob.glob(os.path.join(RAG_DOCS, dirname, ext))
    files = sorted(set(files))
    skipped = 0
    for fp in files:
        txt = read_file_text(fp, max_chars=10 ** 9)   # bez orezania pri indexovaní
        if not txt or txt.startswith("[chyba"):
            skipped += 1
            continue
        first = next((norm(l) for l in txt.splitlines() if len(norm(l)) >= 3), "")
        head = label + (f" — {first}" if 3 <= len(first) <= 90 else "")
        for i, ch in enumerate(chunk_text(txt)):
            out.append({"text": head + "\n" + ch,
                        "source": os.path.basename(fp), "chunk_id": i, "collection": label})
    print(f"[{dirname}] súborov: {len(files)} (preskočené {skipped}) | chunkov: {len(out)}")
    return out


# ---------- 5. embed + FAISS ----------
def build(meta: list[dict]):
    import numpy as np, faiss
    from sentence_transformers import SentenceTransformer
    model = SentenceTransformer("BAAI/bge-m3", device="cpu")
    texts = [m["text"] for m in meta]
    print(f"[embed] {len(texts)} chunkov ...")
    vecs = model.encode(texts, normalize_embeddings=True, batch_size=32,
                        show_progress_bar=True, convert_to_numpy=True).astype("float32")
    idx = faiss.IndexFlatIP(vecs.shape[1])
    idx.add(vecs)
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    faiss.write_index(idx, str(OUT_DIR / "faiss.index"))
    with open(OUT_DIR / "meta.jsonl", "w", encoding="utf-8") as f:
        for m in meta:
            f.write(json.dumps(m, ensure_ascii=False) + "\n")
    write_manifest(meta)
    print(f"[hotovo] {idx.ntotal} chunkov → {OUT_DIR}")


def write_manifest(meta):
    """Zapíše ľudský popis obsahu bázy (pre auto-routing v popise nástroja rag_search)."""
    per = Counter(m.get("collection", "?") for m in meta)
    lines = ["Znalostná báza (rag_search) obsahuje slovenskú literatúru:"]
    for coll, n in per.most_common():
        lines.append(f"• {coll} ({n} pasáží)")
    manifest = "\n".join(lines)
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    (OUT_DIR / "manifest.txt").write_text(manifest, encoding="utf-8")
    print("[manifest]\n" + manifest)


def gather() -> list[dict]:
    meta = valek_chunks()
    for dirname, label in COLLECTIONS:
        meta += collection_chunks(dirname, label)
    return meta


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args()
    meta = gather()
    from collections import Counter as _C
    print("[SPOLU] chunkov:", len(meta), "| podľa kolekcie:", dict(_C(m.get("collection","?") for m in meta)))
    if a.dry_run:
        write_manifest(meta)
    else:
        build(meta)
