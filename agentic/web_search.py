"""Rate-limitovaný DuckDuckGo search — aby nás DDG nezabanoval.

Ochrany:
  - single-flight lock: len JEDEN DDG request naraz (žiadne paralelné volania)
  - min interval medzi requestmi (default 4s)
  - exponenciálny backoff pri rate-limit chybe (5s → 10 → 20 ... cap 120s)
  - TTL cache výsledkov (rovnaký dotaz sa nepýta znova)
  - jitter, aby requesty neboli strojovo pravidelné

Používa knižnicu `ddgs` (udržiavaný nástupca duckduckgo_search).
"""
from __future__ import annotations

import time
import random
import threading
import logging
from typing import List, Dict

log = logging.getLogger("web_search")

_LOCK = threading.Lock()          # single-flight: 1 DDG request naraz
_LAST_CALL = 0.0                  # čas posledného requestu (monotonic)
_MIN_INTERVAL = 4.0              # min sekúnd medzi requestmi
_BACKOFF = 5.0                   # aktuálny backoff (rastie pri rate-limite)
_BACKOFF_MAX = 120.0
_CACHE: Dict[str, tuple] = {}    # query -> (timestamp, results)
_CACHE_TTL = 900.0               # 15 min

try:
    from ddgs import DDGS
except ImportError:  # starší názov balíka
    try:
        from duckduckgo_search import DDGS
    except ImportError:
        DDGS = None


def _throttle():
    """Počká, aby medzi DDG requestmi bol aspoň _MIN_INTERVAL (+ jitter)."""
    global _LAST_CALL
    now = time.monotonic()
    wait = _MIN_INTERVAL - (now - _LAST_CALL) + random.uniform(0, 1.0)
    if wait > 0:
        time.sleep(wait)
    _LAST_CALL = time.monotonic()


def web_search(query: str, max_results: int = 5, region: str = "sk-sk") -> List[Dict]:
    """Vráti zoznam {title, href, body}. Bezpečné voči rate-limitu.

    Pri opakovanom rate-limite vráti prázdny zoznam (nespadne) — agent to ošetrí.
    """
    global _BACKOFF
    if DDGS is None:
        return [{"title": "chyba", "href": "", "body": "ddgs balík nie je nainštalovaný"}]

    key = f"{region}|{max_results}|{query.strip().lower()}"
    cached = _CACHE.get(key)
    if cached and (time.monotonic() - cached[0] < _CACHE_TTL):
        log.info("cache hit: %s", query[:60])
        return cached[1]

    with _LOCK:  # len jeden request naraz naprieč vláknami
        for attempt in range(4):
            _throttle()
            try:
                with DDGS() as ddgs:
                    results = list(ddgs.text(query, region=region,
                                             safesearch="moderate", max_results=max_results))
                # úspech → resetuj backoff
                _BACKOFF = 5.0
                out = [{"title": r.get("title", ""), "href": r.get("href", ""),
                        "body": r.get("body", "")} for r in results]
                _CACHE[key] = (time.monotonic(), out)
                return out
            except Exception as e:
                msg = str(e).lower()
                is_rate = "ratelimit" in msg or "202" in msg or "429" in msg or "403" in msg
                if is_rate and attempt < 3:
                    sleep_s = min(_BACKOFF, _BACKOFF_MAX) + random.uniform(0, 2)
                    log.warning("DDG rate-limit (pokus %d), backoff %.0fs: %s", attempt + 1, sleep_s, e)
                    time.sleep(sleep_s)
                    _BACKOFF = min(_BACKOFF * 2, _BACKOFF_MAX)
                    continue
                log.warning("DDG search zlyhal: %s", e)
                return []
    return []


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    import sys
    q = sys.argv[1] if len(sys.argv) > 1 else "Miroslav Válek básnik"
    for r in web_search(q, max_results=5):
        print("-", r["title"])
        print("  ", r["href"])
        print("  ", r["body"][:150])
