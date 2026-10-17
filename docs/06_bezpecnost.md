# 6. Bezpečnosť

## Zavedené opatrenia (audit júl 2026)

| Oblasť | Opatrenie |
|---|---|
| Verejná plocha | nginx :80 proxuje **len** na agenta (127.0.0.1:8200); model (:8000) ani RAG (:8100) nie sú z internetu dostupné |
| Tunel | dedikovaný kľúč na VM s `restrict,port-forwarding,command=...,permitopen="gpuNN:8200"` — žiadny shell, žiadny iný host/port; osobný kľúč na VM nie je |
| Overenie tunela | `whoami` cez kľúč vráti uzol (forced command), forward na login:22 a na :8000 odmietnutý, forward na :8200 funguje |
| SSRF | `fetch_url` → `_host_is_public`: blokuje privátne, loopback, link-local, reserved a cloud metadata IP, aj po presmerovaní (overené: 10.x, 169.254.169.254, localhost, interné uzly) |
| Path traversal | `/files/{name}` a `/static/{name}` berú len `basename` a overujú, že cesta ostala v adresári |
| Únik promptu | systémový prompt zakazuje prezradiť pokyny (overené) |
| Upload | max 5 MB, do kontextu max 8000 znakov, max 3 prílohy na sedenie |
| Logy | log otázok (IP + obsah) je len na klastri, nie cez web |

## Zostávajúce riziká (nezavedené)

- **Bez autentifikácie a rate-limitu** — verejná IP priťahuje skenery a botov (väčšina
  prevádzky); jeden používateľ môže zahltiť 16 slotov modelu. Riešenie: `limit_req` v nginx,
  prihlasovanie, prípadne Cloudflare.
- **HTTP bez TLS** — treba doménu + Let's Encrypt (`certbot --nginx`).
- **SSH :22 na VM verejné** — obmedziť NSG na známe IP alebo fail2ban.
- **RAG služba na klastri** počúva na `0.0.0.0:8100` a má `POST /rag/index` s ľubovoľnými
  cestami — je dostupná z vnútornej siete klastra (nie z internetu). Pri zdieľanom klastri
  zvážte `host=127.0.0.1` (agent beží na tom istom uzle) alebo odstránenie endpointu.
- Agent a model počúvajú na `0.0.0.0` vnútri siete klastra (tunel ich potrebuje z login uzla).
- `make_file` zapisuje do `PDF_DIR` bez čistenia — pravidelne mazať staré súbory.

## Ochrana osobných údajov

Log otázok obsahuje IP adresy a texty otázok; UI upozorňuje „Nevkladajte citlivé údaje. Údaje
môžu byť použité na trénovanie modelu." Pri prevádzke v EÚ treba GDPR: informovanie
používateľov, doba uchovávania, prístup k logu len pre správcov. Logy, nahraté prílohy a
vytvorené súbory nikdy necommitujte (`.gitignore`).
