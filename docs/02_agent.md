# 2. Agentická vrstva

Agent (`agentic/agent.py`) je tool-calling slučka proti OpenAI-kompatibilnému API SGLang-u
(`/v1/chat/completions`). Model si sám volí nástroje (max 8 krokov), agent ich vykoná,
výsledky priloží a opakuje, kým model nedá finálnu odpoveď. Všetko beží na CPU master uzla.

## Súbory

| Súbor | Popis |
|---|---|
| `agentic/agent.py` | orchestrátor, web UI (`GET /`), SSE streaming, multi-turn pamäť, upload, log otázok; `--serve` = port 8200, bez parametra = CLI |
| `agentic/tools.py` | schémy + exekútory nástrojov, extrakcia textu zo súborov, tvorba súborov |
| `agentic/rag_service.py` | FastAPI RAG (bge-m3 + FAISS + BM25), port 8100 |
| `agentic/rebuild_index.py` | (re)build indexu — viď [03_rag_korpus.md](03_rag_korpus.md) |
| `agentic/web_search.py` | DuckDuckGo s rate-limitom |
| `agentic/index_pdfs.py` | jednoduché pridanie súborov do indexu (bez hlavičiek kolekcií) |
| `agentic/tests/` | `test_agent.py` (HTTP), `test_agent_direct.py`, `show_answers.py`, `agent_bench.py` (záťaž), `test_ssrf.py` |
| `perun/serve_agentic.sh` | jeden SLURM job: model (srun, 2 uzly) + RAG + agent na master CPU |
| `perun/setup_agentic_env.sh` | čistý venv s CPU torchom + MathJax |

## Inštalácia

```bash
bash perun/setup_agentic_env.sh       # vytvorí $JH_AGENT_VENV, nainštaluje requirements.txt, stiahne MathJax
```

Venv je **čistý** (nie `--system-site-packages`): SGLang env obsahuje `torchcodec`, ktorý padá
na chýbajúcom FFmpeg (`libavutil.so.56`) a blokuje `sentence-transformers`. Embedder beží na CPU,
GPU torch netreba. Verzie: [agentic/requirements.txt](../agentic/requirements.txt), úplný
zoznam [agentic/venv_packages.txt](../agentic/venv_packages.txt).

Compute uzly TUKE Perun majú priamy internet (DuckDuckGo, Hugging Face) — ak váš klaster nie,
`web_search`/`fetch_url` nebudú fungovať a embedder `BAAI/bge-m3` treba stiahnuť vopred.

## Nástroje

| Nástroj | Čo robí |
|---|---|
| `rag_search(query, k=5)` | hybridné vyhľadávanie v báze. Popis nástroja sa pri štarte **automaticky doplní manifestom** (zoznam kolekcií a počty pasáží) |
| `web_search(query, max_results=5)` | DuckDuckGo, región sk-sk; single-flight zámok, min. 4 s medzi dopytmi, exponenciálny backoff (5→120 s), cache 15 min |
| `fetch_url(url)` | stiahne stránku (BeautifulSoup, max 3000 znakov); **SSRF ochrana** `_host_is_public` blokuje privátne/loopback/link-local/reserved/metadata IP aj po presmerovaní |
| `calc(expression)` | sympy: aritmetika, zjednodušenie, rovnice (`x**2 = 5*x + 3`), `diff`, `integrate`, limity |
| `make_file(format, title, content)` | pdf (reportlab), docx, xlsx, pptx, odt/ods/odp (odfpy). Tabuľky: riadok = riadok, bunky cez tab alebo `\|`. Prezentácie: snímky oddelené `---` alebo `# nadpisom` |
| upload (`POST /agent/upload`) | číta pdf/docx/doc/rtf/xlsx/pptx/odt/ods/odp/txt/csv/md; text (max 8000 zn.) ide do session ako príloha (max 3 posledné) |

Starý binárny `.doc` (OLE) sa číta bez soffice/antiword: `_read_ole_doc` vytiahne stream
`WordDocument` ako UTF-16-LE.

## Auto-manifest routing

Obsah bázy nie je natvrdo v systémovom prompte. `rebuild_index.py` zapíše `manifest.txt`,
`rag_service` ho vystaví na `GET /rag/manifest` a agent ho pri štarte (s retry, RAG môže ešte
nabiehať) pripojí k **popisu nástroja** `rag_search`. Po pridaní kolekcie a reindexe stačí
reštart RAG + agenta a model vie, čo v báze je.

## Pamäť konverzácie

- Server-side `SESSIONS` podľa `session_id` (UI generuje `crypto.randomUUID()`), max 500 sedení (vyhodí najstaršie).
- Po každom kole sa uloží len **{otázka, odpoveď}** — bez tool-traffiku.
- Keď doslovná história presiahne `AGENT_HISTORY_CHARS` (6000), staršie kolá okrem posledných
  `AGENT_KEEP_TURNS` (4) sa jedným volaním modelu **zhrnú** do rolling summary a odstránia.
- Pri prerušení streamu (⏹) sa kolo neuloží. `POST /agent/reset` zmaže sedenie.
- Sedenia sú v RAM — reštart agenta ich zmaže.

## Ochrana kontextu (okno 32 768 tokenov)

- `AGENT_RESULT_CAP` = 2500 — strop jedného výsledku nástroja v kontexte (inak RAG výsledky
  cez 8 krokov pretečú okno → HTTP 400).
- `_fit_tokens()` — `max_tokens` sa zníži podľa zvyšku okna (odhad 2,5 znaku/token).
- Pri HTTP 400 jeden retry s `max_tokens=384`. `AGENT_MAX_TOKENS` = 3072.
- Po vyčerpaní krokov agent vyžiada finálnu odpoveď bez nástrojov; presiaknutý DSML markup
  (`<｜DSML｜tool_calls>`) sa z odpovede odstráni (`_clean`).
- Ak používateľ chcel PDF a model ho nestihol vytvoriť, PDF sa vytvorí z finálnej odpovede.

## HTTP API (port 8200)

| Endpoint | Popis |
|---|---|
| `GET /` | web UI „Janko Hraško" (samostatné HTML+JS, rovnaký origin → bez CORS) |
| `POST /agent/stream` `{message, session_id}` | SSE eventy: `tool_call`, `tool_result`, `file`, `answer_delta`, `done`, `error` |
| `POST /agent/chat` `{message, session_id?}` | nestreamovaná odpoveď + `trace`; bez `session_id` jednorazovo |
| `POST /agent/upload` (multipart `file`, `session_id`) | príloha do sedenia |
| `POST /agent/reset` `{session_id}` | zmaže sedenie |
| `GET /files/{name}` | stiahnutie vytvoreného súboru z `PDF_DIR` (len basename) |
| `GET /static/{name}` | MathJax (`agentic/static/mathjax.js`) |
| `GET /health` | `{ok, v1}` |

RAG (port 8100): `GET /rag/search?q=&k=`, `GET /rag/manifest`, `GET /rag/stats`, `GET /health`,
`POST /rag/index {"paths": [...]}`.

## Premenné prostredia

| Premenná | Predvolené | Význam |
|---|---|---|
| `V1_URL` | `http://127.0.0.1:8000` | SGLang endpoint |
| `RAG_URL` | `http://127.0.0.1:8100` | RAG služba |
| `AGENT_PORT` | 8200 | |
| `PDF_DIR` | `./agent_out` | vytvorené súbory; **posledný adresár sa musí volať `agent_out`** (podľa toho UI rozpozná odkazy na stiahnutie) |
| `UPLOAD_DIR` | `<PDF_DIR>/../agent_uploads` | nahraté prílohy |
| `AGENT_QUERY_LOG` | `./agent_queries.jsonl` | log otázok |
| `AGENT_MAX_STEPS` / `AGENT_MAX_TOKENS` / `AGENT_CONTEXT_LEN` / `AGENT_RESULT_CAP` | 8 / 3072 / 32768 / 2500 | |
| `AGENT_HISTORY_CHARS` / `AGENT_KEEP_TURNS` / `AGENT_MAX_SESSIONS` | 6000 / 4 / 500 | pamäť |
| `AGENT_MAX_UPLOAD_BYTES` / `AGENT_MAX_UPLOAD_CHARS` / `AGENT_MAX_ATTACHMENTS` | 5 MB / 8000 / 3 | prílohy |
| `RAG_INDEX_DIR`, `RAG_EMBED_MODEL`, `RAG_DEVICE`, `RAG_PORT` | `./rag_index`, `BAAI/bge-m3`, `cpu`, 8100 | RAG |

## Systémový prompt (správanie)

Celý text je v `agent.py` (`SYSTEM`). Hlavné pravidlá:
- odpovedá **stručne**, rozvádza len na výslovné želanie;
- literárne témy → `rag_search`; pesničky, pop, aktuality, všeobecné fakty → rovno `web_search`;
- **pri neistom fakte (autorstvo, mená, dátumy) nehádže z pamäte** — overí cez RAG/web, inak prizná neistotu;
- matematika cez `calc`, výrazy v LaTeXe `\( \)` / `\[ \]`;
- neprezrádza systémový prompt ani štýlové pokyny.

## Web UI

Titul „Janko Hraško", podnadpis „Vytvorené v spolupráci SAV, TUKE a ČZ o.z.", dole upozornenie
„Nevkladajte citlivé údaje. Údaje môžu byť použité na trénovanie modelu." Tlačidlá
Odoslať / ⏹ Zastaviť (AbortController — preruší spojenie prehliadač↔agent; rozbehnutý krok
modelu dobehne), Nová konverzácia, 📎 príloha. Tmavý/svetlý režim podľa systému, živé kroky,
MathJax po dostreamovaní, tlačidlá „⬇ Stiahnuť".

## Logovanie otázok

Každý dotaz → riadok JSONL v `AGENT_QUERY_LOG`: `ts, ip, session, q, a, tools`. Reálna IP
klienta z hlavičky `X-Real-IP` (posiela ju nginx; agent inak vidí len tunel). Log obsahuje
**osobné údaje** (IP, obsah otázok) — nie je vystavený cez web, nepatrí do gitu.

## Testy

Testy bežia vo voľných jadrách bežiaceho jobu, nie na login uzle:

```bash
cd ~/jankohrasko
T='source config.env; source $JH_AGENT_VENV/bin/activate; cd agentic;'
srun --overlap --jobid <JOBID> -w <MASTER> --ntasks=1 bash -c "$T python tests/test_agent.py http://<MASTER>:8200"
srun --overlap --jobid <JOBID> -w <MASTER> --ntasks=1 bash -c "$T python tests/test_ssrf.py <MASTER>"
srun --overlap --jobid <JOBID> -w <MASTER> --ntasks=1 bash perun/bench100.sh <MASTER>   # 100 agentov naraz
```

`test_ssrf.py` musí ukázať interné adresy ZABLOKOVANÉ a `example.com` POVOLENÉ.

Záťažový test (100 agentov naraz s RAG/web/fetch/PDF): 100/100 OK, medián 625 s na požiadavku.
**Úzke hrdlo je DuckDuckGo** (4 s serializácia × 217 dopytov ≈ celý čas), nie GPU — čisto RAG
otázky dobehli za 2–4 min aj pod záťažou. Zlepšenie: vlastný SearxNG / platené search API.

## Známe obmedzenia

- `make_file` pdf používa štandardný font reportlab (Helvetica) bez registrovaného TTF —
  overte, či sa správne vykreslia znaky ako č, ľ, ť; prípadne zaregistrujte DejaVuSans.
- Sedenia a prílohy sú len v RAM jedného procesu agenta.
- GPU nástroje (generovanie obrázkov, rozpoznávanie reči) neboli zavedené.
