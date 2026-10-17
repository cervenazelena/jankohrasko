# Janko Hraško

Slovenský AI asistent: veľký jazykový model **DeepSeek-V4-Pro** na superpočítači
(2 uzly × 8× NVIDIA H200), nad ním **agentická vrstva** (vyhľadávanie v literárnej
znalostnej báze, web, presné výpočty, tvorba a čítanie kancelárskych súborov, pamäť
konverzácie) a **verejné webové rozhranie** cez malý Azure VM napojený na sieť klastra cez VPN.

*Vytvorené v spolupráci SAV, TUKE a ČZ o.z.* Referenčné nasadenie bežalo v júli 2026 na
superpočítači TUKE Perun.

Toto repo obsahuje všetok kód, skripty a postup, podľa ktorých sa dá systém zreplikovať.

## Architektúra

```
  Používateľ (prehliadač)
        │  http://<PUBLIC_IP>
        ▼
  Azure VM (Ubuntu 22.04, Standard_D2s_v3)
     nginx :80  ──►  127.0.0.1:8200 (autossh tunel, forward-only kľúč)
        │  cez VPN (Pritunl) do siete klastra
        ▼
  login uzol klastra  ──►  <gpu-uzol>:8200   (compute uzly nie sú verejné)
        ▼
  SLURM job „sglang_agentic" (2 uzly × 8× H200), na MASTER uzle:
     :8200  agent.py        orchestrátor + web UI + nástroje (CPU)
     :8100  rag_service.py  hybrid RAG: bge-m3 + FAISS + BM25 (CPU)
     :8000  SGLang          DeepSeek-V4-Pro-FP8, TP=16 / EP=16 cez InfiniBand (16 GPU)
```

Model, RAG aj agent bežia v **jednom** SLURM jobe: model zaberie GPU a ~32 zo 128 CPU jadier
uzla, RAG a agent využívajú zvyšné jadrá (co-location).

## Čo vie

| Schopnosť | Ako |
|---|---|
| Odpovede zo slovenskej literatúry | `rag_search` — hybridné vyhľadávanie (dense bge-m3 + BM25, RRF) v ~9 tis. pasážach |
| Aktuálne fakty | `web_search` (DuckDuckGo, rate-limit) + `fetch_url` (so SSRF ochranou) |
| Matematika | `calc` cez sympy (rovnice, derivácie, integrály), výstup v LaTeXu (MathJax) |
| Tvorba súborov | `make_file`: pdf, docx, xlsx, pptx, odt, ods, odp → tlačidlo „⬇ Stiahnuť" |
| Čítanie príloh | upload pdf/docx/doc/rtf/xlsx/pptx/odt/ods/odp/txt (do 5 MB, ~8000 zn. do kontextu) |
| Pamäť konverzácie | doslovné posledné kolá + priebežné zhrnutie starších (neobmedzená dĺžka) |
| Streaming | SSE — UI ukazuje živé kroky (🔎 🌐 📄 🧮 📝) a postupne písanú odpoveď |

Namerané (2 uzly, 16× H200): 19,6 tok/s pre jedného používateľa; 100 súbežných
používateľov = 17 tok/s na používateľa, 1535 tok/s spolu, TTFT 0,7 s, 100/100 OK.

## Štruktúra repa

```
config.example.env      cesty a prostredia (skopíruj na config.env)
server/                 model server: inštalácia SGLang, DeepEP, stiahnutie modelu, patch, diagnostika
perun/                  SLURM: hlavný job (model+RAG+agent), venv agenta, reindex, reštarty
agentic/                agent.py, tools.py, rag_service.py, rebuild_index.py, web_search.py, testy
azure/                  frontend VM: nginx, autossh tunel, systemd, SSH obmedzenia
docs/                   podrobný návod (kapitoly nižšie)
```

## Replikácia — postup

| # | Krok | Kde | Návod |
|---|---|---|---|
| 1 | Admin nastavenie GPU uzlov (nvidia_peermem, GDRCopy, `PeerMappingOverride=1`) | správcovia klastra | [01](docs/01_model_server.md#1-predpoklady-na-uzloch-admin) |
| 2 | `cp config.example.env config.env` a uprav cesty | login uzol | [01](docs/01_model_server.md#2-konfigurácia) |
| 3 | SGLang env + MNNVL patch + DeepEP | `server/setup_sglang.sh`, `server/build_deepep.sh` | [01](docs/01_model_server.md#3-sglang-prostredie) |
| 4 | Stiahnuť model (~1,6 TB) | `server/download_model.sh` | [01](docs/01_model_server.md#4-model) |
| 5 | Overiť DeepEP medzi uzlami (2 min) | `server/test_deepep_internode.sh` | [01](docs/01_model_server.md#5-test-deepep-medzi-uzlami) |
| 6 | Venv agenta (CPU torch) + MathJax | `perun/setup_agentic_env.sh` | [02](docs/02_agent.md#inštalácia) |
| 7 | Vložiť texty a postaviť RAG index | `perun/build_index.sh` | [03](docs/03_rag_korpus.md) |
| 8 | Spustiť celý stack (~18 min boot) | `sbatch -A <ACC> --qos <QOS> perun/serve_agentic.sh` | [01](docs/01_model_server.md#6-spustenie), [05](docs/05_prevadzka.md) |
| 9 | Verejný frontend (VM, VPN, tunel, nginx) | `azure/setup_vm.sh` | [04](docs/04_frontend_azure.md) |

Lokálny prístup bez frontendu: `ssh -N -L 8200:<master-uzol>:8200 <user>@<login>` a otvoriť
`http://localhost:8200`.

## Dokumentácia

1. [Model server — DeepSeek-V4-Pro na 2 uzloch](docs/01_model_server.md)
2. [Agentická vrstva](docs/02_agent.md)
3. [RAG korpus a indexovanie](docs/03_rag_korpus.md)
4. [Verejný frontend na Azure](docs/04_frontend_azure.md)
5. [Prevádzka (cheatsheet)](docs/05_prevadzka.md)
6. [Bezpečnosť](docs/06_bezpecnost.md)

## Čo v repe nie je

- **Váhy modelu** — `sgl-project/DeepSeek-V4-Pro-FP8` z Hugging Face (`server/download_model.sh`).
- **Texty znalostnej bázy** (Válkovo básnické dielo, Slovník diel slovenskej literatúry
  19./20. st., Sondy do slovenskej literatúry 19./20. st.) — chránené autorským právom.
  [docs/03](docs/03_rag_korpus.md) opisuje ich štruktúru a ako použiť vlastné texty.
- **Index RAG, logy otázok, prístupové údaje** (VPN profil, heslá, kľúče, IP adresy).
- **MathJax** — stiahne `perun/fetch_mathjax.sh` (Apache-2.0).

## Licencia

MIT — viď [LICENSE](LICENSE). Model DeepSeek-V4-Pro a knižnice tretích strán majú vlastné licencie.
