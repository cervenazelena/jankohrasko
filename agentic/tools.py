"""Definície nástrojov pre agenta (OpenAI function-calling formát) + exekútory.

Nástroje:
  - rag_search   : lokálny RAG (volá rag_service.py)
  - web_search   : DuckDuckGo (rate-limitovaný, web_search.py)
  - make_pdf     : vygeneruje PDF (reportlab) a vráti cestu

Env:
  RAG_URL   (default http://127.0.0.1:8100)
  PDF_DIR   (default ./agent_out)
"""
from __future__ import annotations

import os
import json
import time
import logging
import urllib.parse
import urllib.request
from pathlib import Path

from web_search import web_search as _ddg

log = logging.getLogger("tools")

RAG_URL = os.environ.get("RAG_URL", "http://127.0.0.1:8100")
PDF_DIR = Path(os.environ.get("PDF_DIR", "./agent_out"))

# ---------- OpenAI tool schémy (pošlú sa modelu) ----------
TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "rag_search",
            "description": (
                "Vyhľadá presné pasáže v LOKÁLNEJ literárnej znalostnej báze (plné texty diel, "
                "hesiel a štúdií). Pre témy, ktoré do bázy patria, je to autoritatívny primárny "
                "zdroj — preferuj ho pred webom. Presný obsah bázy je uvedený nižšie."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "vyhľadávací dotaz"},
                    "k": {"type": "integer", "description": "počet pasáží (default 5)"},
                },
                "required": ["query"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "web_search",
            "description": "Vyhľadá aktuálne informácie na internete cez DuckDuckGo. Použi na aktuálne/verejné fakty, ktoré nie sú v lokálnych dokumentoch.",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "vyhľadávací dotaz"},
                    "max_results": {"type": "integer", "description": "počet výsledkov (default 5)"},
                },
                "required": ["query"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "fetch_url",
            "description": (
                "Stiahne konkrétnu webovú stránku a vráti jej textový obsah (orezaný). "
                "Použi po web_search, keď potrebuješ prečítať CELÝ obsah konkrétnej nájdenej "
                "stránky — napr. heslo v encyklopédii, článok, detail. web_search dáva len "
                "krátke úryvky; fetch_url dá plný text danej URL."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "url": {"type": "string", "description": "úplná URL adresa stránky"},
                },
                "required": ["url"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "calc",
            "description": (
                "Presný matematický výpočet cez sympy (nie odhad spamäti). Aritmetika, "
                "zjednodušenie výrazov, riešenie rovníc, derivácie, integrály, limity. "
                "Zadaj výraz alebo rovnicu v Python/sympy syntaxi, napr. '(5+sqrt(37))/2', "
                "'x**2 = 5*x + 3', 'integrate(sin(x), x)', 'diff(x**3, x)'. "
                "Použi vždy, keď treba GARANTOVANE správny číselný alebo symbolický výsledok."
            ),
            "parameters": {
                "type": "object",
                "properties": {"expression": {"type": "string", "description": "výraz alebo rovnica"}},
                "required": ["expression"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "make_file",
            "description": (
                "Vytvorí súbor z daného obsahu a vráti cestu (používateľ si ho stiahne). "
                "Podporované formáty: pdf, docx (Word), xlsx (Excel), pptx (PowerPoint), "
                "odt/ods/odp (LibreOffice text/tabuľka/prezentácia). "
                "Pre tabuľky (xlsx/ods): každý riadok obsahu = riadok tabuľky, bunky oddeľ "
                "tabulátorom alebo znakom '|'. Pre prezentácie (pptx/odp): snímky oddeľ riadkom "
                "'---' alebo nadpisom začínajúcim '#'; prvý riadok snímky je nadpis, ďalšie sú body."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "format": {"type": "string",
                               "description": "pdf | docx | xlsx | pptx | odt | ods | odp"},
                    "title": {"type": "string"},
                    "content": {"type": "string", "description": "telo dokumentu"},
                },
                "required": ["format", "title", "content"],
            },
        },
    },
]


# ---------- exekútory ----------
def _http_get(url: str, params: dict, timeout: int = 30) -> dict:
    full = url + "?" + urllib.parse.urlencode(params)
    with urllib.request.urlopen(full, timeout=timeout) as r:
        return json.loads(r.read())


def exec_rag_search(query: str, k: int = 5) -> str:
    try:
        j = _http_get(f"{RAG_URL}/rag/search", {"q": query, "k": k})
        res = j.get("results", [])
        if not res:
            return "Žiadne relevantné pasáže v lokálnej báze."
        return "\n\n".join(
            f"[{i+1}] ({r['source']} #{r['chunk_id']}, skóre {r['score']:.2f})\n{r['text']}"
            for i, r in enumerate(res)
        )
    except Exception as e:
        return f"RAG chyba: {e}"


def exec_web_search(query: str, max_results: int = 5) -> str:
    res = _ddg(query, max_results=max_results)
    if not res:
        return "Web search nevrátil výsledky (možno rate-limit, skús neskôr)."
    return "\n\n".join(
        f"[{i+1}] {r['title']}\n{r['href']}\n{r['body'][:300]}"
        for i, r in enumerate(res)
    )


def _host_is_public(host: str) -> bool:
    """True len ak sa VŠETKY IP hostiteľa dajú a nie sú privátne/loopback/link-local/reserved.
    Bráni SSRF — agent beží na Perune, nesmie fetchovať interné adresy ani cloud metadata."""
    import socket
    import ipaddress
    if not host:
        return False
    try:
        infos = socket.getaddrinfo(host, None)
    except Exception:
        return False
    for info in infos:
        try:
            ip = ipaddress.ip_address(info[4][0])
        except Exception:
            return False
        if (ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved
                or ip.is_multicast or ip.is_unspecified):
            return False
    return True


class _NoInternalRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        from urllib.parse import urlparse
        if not _host_is_public(urlparse(newurl).hostname or ""):
            return None                     # zablokuj presmerovanie na interné
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def exec_fetch_url(url: str, max_chars: int = 3000) -> str:
    """Stiahne stránku a vráti extrahovaný text (orezaný). So SSRF ochranou."""
    if not url.startswith(("http://", "https://")):
        return "Neplatná URL (musí začínať http:// alebo https://)."
    from urllib.parse import urlparse
    if not _host_is_public(urlparse(url).hostname or ""):
        return "Zamietnuté: interné/privátne adresy nie sú povolené."
    try:
        opener = urllib.request.build_opener(_NoInternalRedirect())
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 (agent)"})
        with opener.open(req, timeout=25) as r:
            raw = r.read(600_000).decode("utf-8", "replace")
        try:
            from bs4 import BeautifulSoup
            soup = BeautifulSoup(raw, "html.parser")
            for tag in soup(["script", "style", "nav", "header", "footer", "noscript"]):
                tag.decompose()
            text = soup.get_text("\n")
        except Exception:
            import re as _re
            text = _re.sub(r"<[^>]+>", " ", raw)
        # zhusti prázdne riadky, orež
        import re as _re
        text = _re.sub(r"\n\s*\n+", "\n\n", text)
        text = _re.sub(r"[ \t]+", " ", text).strip()
        if len(text) > max_chars:
            text = text[:max_chars] + "\n…[skrátené]"
        return f"[obsah {url}]\n{text}"
    except Exception as e:
        return f"fetch_url chyba pri {url}: {e}"


def exec_calc(expression: str) -> str:
    try:
        import sympy as sp
        from sympy.parsing.sympy_parser import (parse_expr, standard_transformations,
                                                implicit_multiplication_application, convert_xor)
    except Exception as e:
        return f"sympy nedostupné: {e}"
    expr = (expression or "").strip().rstrip(".")
    if not expr:
        return "Prázdny výraz."
    tr = standard_transformations + (implicit_multiplication_application, convert_xor)
    try:
        if "=" in expr and "==" not in expr:                 # rovnica
            lhs, rhs = expr.split("=", 1)
            eq = sp.Eq(parse_expr(lhs, transformations=tr), parse_expr(rhs, transformations=tr))
            syms = sorted(eq.free_symbols, key=lambda s: s.name)
            sols = sp.solve(eq, syms, dict=True) if syms else []
            if not sols:
                return f"Rovnica {expr}: bez riešenia alebo identita."
            lines = [f"Riešenie {expr}:"]
            for sol in sols:
                for s, v in sol.items():
                    approx = sp.N(v, 6)
                    lines.append(f"  {s} = {v}" + (f" ≈ {approx}" if str(approx) != str(v) else ""))
            return "\n".join(lines)
        e = parse_expr(expr, transformations=tr)             # výraz
        simp = sp.simplify(e)
        res = f"{expr} = {simp}"
        try:
            approx = sp.N(simp, 10)
            if str(approx) != str(simp):
                res += f" ≈ {approx}"
        except Exception:
            pass
        return res
    except Exception as ex:
        return f"calc chyba: {ex}"


def _out_path(title: str, ext: str) -> Path:
    PDF_DIR.mkdir(parents=True, exist_ok=True)
    safe = "".join(c if c.isalnum() or c in " -_" else "_" for c in title)[:60].strip()
    return PDF_DIR / f"{safe or 'dokument'}_{int(time.time())}.{ext}"


def _rows_from_content(content: str):
    """Rozdelí text na riadky/bunky pre tabuľky: bunky oddelené tabulátorom, '|' alebo ';'/','."""
    rows = []
    for line in content.splitlines():
        if not line.strip():
            continue
        if "\t" in line:
            cells = line.split("\t")
        elif "|" in line:
            cells = [c.strip() for c in line.strip().strip("|").split("|")]
        elif ";" in line:
            cells = [c.strip() for c in line.split(";")]
        else:
            cells = [c.strip() for c in line.split(",")]
        rows.append(cells)
    return rows


def _slides_from_content(content: str):
    """Rozdelí text na snímky: oddeľovač '---' alebo riadky začínajúce '#'. Prvý riadok = nadpis."""
    blocks, cur = [], []
    for line in content.splitlines():
        if line.strip() == "---" or (line.startswith("#") and cur):
            if cur:
                blocks.append(cur); cur = []
            if line.startswith("#"):
                cur.append(line.lstrip("# ").strip())
        else:
            cur.append(line)
    if cur:
        blocks.append(cur)
    slides = []
    for b in blocks:
        b = [x for x in b if x.strip()]
        if not b:
            continue
        title = b[0].lstrip("# ").strip()
        bullets = [x.lstrip("-• ").strip() for x in b[1:]]
        slides.append((title, bullets))
    return slides


def exec_make_pdf(title: str, content: str) -> str:
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import getSampleStyleSheet
    from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer
    from reportlab.lib.units import cm
    path = _out_path(title, "pdf")
    doc = SimpleDocTemplate(str(path), pagesize=A4,
                            leftMargin=2*cm, rightMargin=2*cm, topMargin=2*cm, bottomMargin=2*cm)
    styles = getSampleStyleSheet()
    story = [Paragraph(title, styles["Title"]), Spacer(1, 0.5*cm)]
    for para in content.split("\n"):
        para = para.strip()
        if para:
            story.append(Paragraph(para.replace("&", "&amp;").replace("<", "&lt;"), styles["Normal"]))
            story.append(Spacer(1, 0.2*cm))
    doc.build(story)
    return str(path)


def _make_docx(title, content):
    from docx import Document
    d = Document()
    d.add_heading(title, level=0)
    for para in content.split("\n"):
        para = para.strip()
        if para:
            d.add_paragraph(para)
    path = _out_path(title, "docx")
    d.save(str(path))
    return str(path)


def _make_xlsx(title, content):
    from openpyxl import Workbook
    wb = Workbook(); ws = wb.active; ws.title = title[:30] or "Hárok"
    for row in _rows_from_content(content):
        ws.append(row)
    path = _out_path(title, "xlsx")
    wb.save(str(path))
    return str(path)


def _make_pptx(title, content):
    from pptx import Presentation
    from pptx.util import Pt
    prs = Presentation()
    # titulná snímka
    s = prs.slides.add_slide(prs.slide_layouts[0])
    s.shapes.title.text = title
    for stitle, bullets in _slides_from_content(content):
        sl = prs.slides.add_slide(prs.slide_layouts[1])
        sl.shapes.title.text = stitle
        tf = sl.placeholders[1].text_frame
        tf.text = bullets[0] if bullets else ""
        for b in bullets[1:]:
            p = tf.add_paragraph(); p.text = b
    path = _out_path(title, "pptx")
    prs.save(str(path))
    return str(path)


def _make_odf(title, content, kind):
    """kind: 'odt' (text) | 'ods' (tabuľka) | 'odp' (prezentácia)."""
    if kind == "odt":
        from odf.opendocument import OpenDocumentText
        from odf.text import H, P
        doc = OpenDocumentText()
        doc.text.addElement(H(outlinelevel=1, text=title))
        for para in content.split("\n"):
            if para.strip():
                doc.text.addElement(P(text=para.strip()))
    elif kind == "ods":
        from odf.opendocument import OpenDocumentSpreadsheet
        from odf.table import Table, TableRow, TableCell
        from odf.text import P
        doc = OpenDocumentSpreadsheet()
        table = Table(name=title[:30] or "Hárok")
        for row in _rows_from_content(content):
            tr = TableRow()
            for cell in row:
                tc = TableCell(); tc.addElement(P(text=str(cell))); tr.addElement(tc)
            table.addElement(tr)
        doc.spreadsheet.addElement(table)
    else:  # odp
        from odf.opendocument import OpenDocumentPresentation
        from odf.style import MasterPage, PageLayout, PageLayoutProperties
        from odf.draw import Page, Frame, TextBox
        from odf.text import P
        doc = OpenDocumentPresentation()
        pl = PageLayout(name="pl1")
        pl.addElement(PageLayoutProperties(margin="0cm", pagewidth="28cm",
                                           pageheight="21cm", printorientation="landscape"))
        doc.automaticstyles.addElement(pl)
        mp = MasterPage(name="mp1", pagelayoutname="pl1")
        doc.masterstyles.addElement(mp)
        for stitle, bullets in (_slides_from_content(content) or [(title, [])]):
            page = Page(masterpagename="mp1")
            tb = TextBox()
            tb.addElement(P(text=stitle))
            for b in bullets:
                tb.addElement(P(text="• " + b))
            frame = Frame(width="24cm", height="14cm", x="2cm", y="2cm")
            frame.addElement(tb); page.addElement(frame); doc.presentation.addElement(page)
    path = _out_path(title, kind)
    doc.save(str(path))
    return str(path)


_WRITERS = {
    "pdf": exec_make_pdf, "docx": _make_docx, "xlsx": _make_xlsx, "pptx": _make_pptx,
    "odt": lambda t, c: _make_odf(t, c, "odt"),
    "ods": lambda t, c: _make_odf(t, c, "ods"),
    "odp": lambda t, c: _make_odf(t, c, "odp"),
}


def exec_make_file(fmt: str, title: str, content: str) -> str:
    fmt = (fmt or "pdf").lower().lstrip(".")
    w = _WRITERS.get(fmt)
    if not w:
        return f"Nepodporovaný formát '{fmt}'. Podporované: {', '.join(_WRITERS)}."
    try:
        path = w(title or "dokument", content or "")
        return f"Súbor vytvorený ({fmt}): {path}"
    except Exception as e:
        return f"Chyba pri tvorbe {fmt}: {e}"


# ---------- čítanie súborov (upload aj indexovanie) ----------
def _read_ole_doc(path: str) -> str:
    """Starý binárny Word .doc (OLE) — text z WordDocument streamu (utf-16-le)."""
    import re as _re
    import olefile
    ole = olefile.OleFileIO(path)
    data = ole.openstream("WordDocument").read()
    ole.close()
    t = data.decode("utf-16-le", "ignore")
    runs = _re.findall(r"[0-9A-Za-zÀ-ž \t.,;:!?()\-–—\"„“'’/%\n]{20,}", t)
    return _re.sub(r"[ \t]{2,}", " ", "\n".join(r.strip() for r in runs)).strip()


def read_file_text(path: str, max_chars: int = 8000) -> str:
    """Extrahuje text zo súboru (pdf/docx/doc/rtf/xlsx/pptx/odt/ods/odp/txt/csv/md...)."""
    p = Path(path)
    suf = p.suffix.lower()
    try:
        if suf == ".pdf":
            import fitz
            doc = fitz.open(str(p))
            text = "\n".join(pg.get_text("text") for pg in doc)
        elif suf == ".rtf":
            from striprtf.striprtf import rtf_to_text
            text = rtf_to_text(p.read_text(encoding="utf-8", errors="replace"))
        elif suf == ".doc":
            with open(p, "rb") as fh:
                head = fh.read(4)
            if head[:2] == b"PK":            # docx premenované na .doc
                from docx import Document
                text = "\n".join(par.text for par in Document(str(p)).paragraphs)
            else:                            # skutočný OLE .doc
                text = _read_ole_doc(str(p))
        elif suf == ".docx":
            from docx import Document
            text = "\n".join(par.text for par in Document(str(p)).paragraphs)
        elif suf == ".xlsx":
            from openpyxl import load_workbook
            wb = load_workbook(str(p), read_only=True, data_only=True)
            parts = []
            for ws in wb.worksheets:
                parts.append(f"# Hárok: {ws.title}")
                for row in ws.iter_rows(values_only=True):
                    parts.append("\t".join("" if c is None else str(c) for c in row))
            text = "\n".join(parts)
        elif suf == ".pptx":
            from pptx import Presentation
            parts = []
            for i, sl in enumerate(Presentation(str(p)).slides, 1):
                parts.append(f"# Snímka {i}")
                for sh in sl.shapes:
                    if sh.has_text_frame:
                        parts.append(sh.text_frame.text)
            text = "\n".join(parts)
        elif suf in (".odt", ".ods", ".odp"):
            from odf.opendocument import load
            from odf import teletype
            doc = load(str(p))
            text = teletype.extractText(doc.body)
        else:  # txt/csv/md/json/...
            text = p.read_text(encoding="utf-8", errors="replace")
    except Exception as e:
        return f"[chyba pri čítaní {p.name}: {e}]"
    text = text.strip()
    if len(text) > max_chars:
        text = text[:max_chars] + f"\n…[skrátené, súbor má viac než {max_chars} znakov]"
    return text


DISPATCH = {
    "rag_search": lambda a: exec_rag_search(a.get("query", ""), int(a.get("k", 5))),
    "web_search": lambda a: exec_web_search(a.get("query", ""), int(a.get("max_results", 5))),
    "fetch_url": lambda a: exec_fetch_url(a.get("url", "")),
    "calc": lambda a: exec_calc(a.get("expression", "")),
    "make_pdf": lambda a: exec_make_pdf(a.get("title", "dokument"), a.get("content", "")),
    "make_file": lambda a: exec_make_file(a.get("format", "pdf"), a.get("title", "dokument"),
                                          a.get("content", "")),
}


def run_tool(name: str, args: dict) -> str:
    fn = DISPATCH.get(name)
    if not fn:
        return f"Neznámy nástroj: {name}"
    log.info("nástroj %s(%s)", name, {k: str(v)[:40] for k, v in args.items()})
    return fn(args)
