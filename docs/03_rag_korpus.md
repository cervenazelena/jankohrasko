# 3. RAG korpus a indexovanie

## Obsah referenčnej bázy

Referenčné nasadenie malo **9094 pasáží v 5 kolekciách** (371 súborov: 357 rtf, 13 docx, 1 doc + 1 PDF):

| Kolekcia | Adresár v `$JH_RAG_DOCS` | Súborov | Pasáží |
|---|---|---|---|
| Básnické dielo Miroslava Válka | `Valek_Basnicke_dielo.pdf` | 1 | 1116 |
| Slovník diel slovenskej literatúry 19. storočia | `slovnik19/` | 111 | 1392 |
| Slovník diel slovenskej literatúry 20. storočia | `slovnik20/` | 200 | 2430 |
| Sondy do slovenskej literatúry 19. storočia | `sondy19/` | 22 | 1516 |
| Sondy do slovenskej literatúry 20. storočia | `sondy20/` | 38 | 2640 |

Texty **nie sú súčasťou repa** (autorské práva). Kto ich má k dispozícii, vloží ich do tejto
štruktúry; inak sa dá použiť ľubovoľný vlastný korpus.

```
$JH_RAG_DOCS/
  Valek_Basnicke_dielo.pdf      # voliteľné — ak chýba, preskočí sa
  slovnik19/*.rtf|docx|doc|txt  # 1 súbor = 1 heslo/štúdia, PRVÝ riadok = názov
  slovnik20/...
  sondy19/...
  sondy20/...
```

## Vlastný korpus

V `agentic/rebuild_index.py` uprav zoznam `COLLECTIONS` — dvojice
`(podadresár, „ľudský názov kolekcie")`. Každý súbor sa rozseká na pasáže a každá pasáž dostane
hlavičku `„<názov kolekcie> — <prvý riadok súboru>"` (pomáha embedderu aj modelu pri citovaní).
Podporované formáty: rtf, docx, doc (OLE), txt (cez `tools.read_file_text`). Názvy kolekcií
a počty pasáží sa zapíšu do `manifest.txt` → agent ich automaticky uvidí v popise nástroja
`rag_search` (žiadna zmena systémového promptu).

## Build indexu

```bash
cd ~/jankohrasko && source config.env
# 1) suchý beh — extrakcia, segmentácia, manifest; bez embeddingu
srun --overlap --jobid <JOBID> -w <MASTER> --ntasks=1 bash perun/build_index.sh --dry-run
# 2) ostrý beh → ${JH_RAG_INDEX}_v2 (živý index sa nedotkne)
srun --overlap --jobid <JOBID> -w <MASTER> --ntasks=1 bash perun/build_index.sh
# 3) výmena + reštart RAG a agenta
mv "$JH_RAG_INDEX" "${JH_RAG_INDEX}_prev" && mv "${JH_RAG_INDEX}_v2" "$JH_RAG_INDEX"
nohup srun --overlap --jobid <JOBID> -w <MASTER> --ntasks=1 bash perun/rag_restart.sh &
nohup srun --overlap --jobid <JOBID> -w <MASTER> --ntasks=1 bash perun/agent_restart.sh <MASTER> &
```

Indexuje sa **na CPU, nikdy nie na login uzle** — buď vo voľných jadrách bežiaceho jobu
(`srun --overlap`), alebo samostatným CPU jobom (`sbatch -p cpu_short ... perun/build_index.sh`).
Pozor na globálny limit uzlov na účet (na TUKE: GPU + CPU joby spolu).

Služby po reštarte spúšťajte ako **perzistentný srun step** (`nohup srun ... &`) — obyčajný
`nohup` vnútri krátkeho srun kroku SLURM pri upratovaní cgroup zabije.

## Ako funguje vyhľadávanie (`rag_service.py`)

- **Dense:** `BAAI/bge-m3` (silný multilingválny model, dobrý pre slovenčinu) na CPU,
  normalizované vektory, FAISS `IndexFlatIP` (kosínus). `OMP_NUM_THREADS=48`.
- **Sparse:** BM25 (`rank_bm25`) postavený pri štarte z `meta.jsonl`. Tokenizácia: lowercase +
  **prefixový stemming** — slová dlhšie než 6 znakov sa skrátia na 6 (hrdzavá / hrdzavú /
  hrdzavého → `hrdzav`), aby sa spárovali slovenské pádové tvary.
- **Fúzia:** reciprocal rank fusion (k=60) z top-30 oboch zložiek. Dense chytá parafrázy,
  BM25 presné slová (verše, citáty, mená).
- Pasáže: 700 znakov, prekryv 120, delenie po odsekoch.
- Skóre RRF je malé (~0,03 aj pri dobrej zhode) — na prahovanie relevancie by bolo treba surový kosínus.

## Válkovo PDF — rotované dvojstrany

Skenované vydanie má strany **otočené o 270°** a každá PDF strana sú **dve knižné strany vedľa
seba** (text zvislý, `line["dir"] == (0, 1)`). pypdf aj predvolená extrakcia PyMuPDF riadky
poprehadzujú. Riešenie v `rebuild_index.py`:

1. slová cez `page.get_text("words")`, stred každého slova transformovať do vizuálneho
   priestoru cez `page.rotation_matrix`;
2. rozdeliť na dva stĺpce podľa **vizuálnej stredovej osi** (deliť len ak obe polovice majú ≥ 15 % slov);
3. v stĺpci zoskupiť slová do riadkov podľa vizuálneho y (tolerancia 7 px), stĺpce zoradiť
   podľa čísla knižnej strany → súvislý text v poradí čítania;
4. **segmentácia po básňach** podľa obsahu (TOC s bodkovými čiarami): prvý výskyt titulu v tele
   = začiatok básne; viacriadkové tituly, CAPS názvy zbierok, extra titul „1944";
5. hlavička pasáže: `„Básnické dielo Miroslava Válka — <báseň> (zbierka <zbierka>)"`.

Výsledok: 216 z 284 titulov zhodených, každá báseň samostatne. Overenie: otázka „Kto je tá
hrdzavá v básni Sluch?" nájde pasáž priamo v Sluchu (predtým ju rozbitá extrakcia stratila).

Táto časť je špecifická pre jedno PDF; pri inom PDF ju netreba (`valek_chunks` sa preskočí,
ak súbor chýba).
