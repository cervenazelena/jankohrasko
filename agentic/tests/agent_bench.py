"""Concurrency + timing test agentickej slučky. Ťažké viacvrstvové otázky o Slovensku,
ktoré nútia použiť RAG (Válek) aj web (aktuálne fakty) — BEZ nápovedy metódy v otázke.

Meria: per-request čas, počet krokov, ktoré nástroje si model vybral (rag vs web),
úspešnosť. Testuje tool-selection (či na to príde sám).

Použitie:
  V1_URL=http://<uzol>:8000 RAG_URL=http://<uzol>:8100 python agent_bench.py --concurrency 1,3,5
"""
import os, sys, time, json, argparse, threading
from concurrent.futures import ThreadPoolExecutor, as_completed

os.environ.setdefault("V1_URL", "http://127.0.0.1:8000")
os.environ.setdefault("RAG_URL", "http://127.0.0.1:8100")
os.environ.setdefault("PDF_DIR", "./agent_out")
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
import agent

# Ťažké, viacvrstvové — ŽIADNA nápoveda "použi rag/web/fetch" — model si volí sám.
# Pokrývajú: fetch_url (konkrétna stránka), make_pdf, web (piesne/aktuálne), RAG (Válek + slovník).
QUESTIONS = [
    "O čom je stránka https://www.cervenazelena.sk/velke-dielo-doktora-konopku/ a má nejaký "
    "súvis s Válkovou poéziou?",

    "Z ktorej básne sú verše „ako by ich jedna mater mala, jedna mater mala, v mliečku "
    "kúpavala“? Odpoveď ulož do PDF súboru.",

    "O čom hovorí pieseň, v ktorej sa spieva „a odvtedy sa podvádzam, že Kristínka iba spí“?",

    "Prečo sa v piesni spieva „kľúče nechal svojim bratom, cez plece sa za ním obzerá“? "
    "Čo tým text vyjadruje?",

    "Kto alebo čo je „tá hrdzavá“ v básni Sluch?",

    "Miroslav Válek debutoval básnickou zbierkou koncom 50. rokov. Ako sa volá a koľko "
    "obyvateľov má dnes mesto, kde sa narodil?",

    "Čoho vrcholom je Sládkovičova básnická skladba Marína a čo bolo podnetom jej napísania?",

    "Kto je súčasným ministrom kultúry SR a akú najvyššiu kultúrnu funkciu zastával Válek?",
]


def one(qi: int) -> dict:
    q = QUESTIONS[qi % len(QUESTIONS)]
    t0 = time.time()
    try:
        out = agent.run_agent(q)
        dt = time.time() - t0
        tools = [t["tool"] for t in out.get("trace", [])]
        return {"ok": True, "qi": qi, "dt": dt, "steps": out.get("steps"),
                "n_rag": tools.count("rag_search"), "n_web": tools.count("web_search"),
                "n_pdf": tools.count("make_pdf"),
                "answer": out.get("answer", ""), "q": q}
    except Exception as e:
        return {"ok": False, "qi": qi, "dt": time.time() - t0, "err": repr(e), "q": q}


def run_level(conc: int, verbose: bool):
    print(f"\n{'='*90}\n### CONCURRENCY = {conc} ###")
    wall0 = time.time()
    results = []
    with ThreadPoolExecutor(max_workers=conc) as ex:
        futs = [ex.submit(one, i) for i in range(conc)]
        for f in as_completed(futs):
            results.append(f.result())
    wall = time.time() - wall0
    ok = [r for r in results if r["ok"]]
    times = sorted(r["dt"] for r in ok)
    if ok:
        p50 = times[len(times)//2]
        print(f"OK {len(ok)}/{conc} | čas/req: min {times[0]:.0f}s  p50 {p50:.0f}s  max {times[-1]:.0f}s | "
              f"wall {wall:.0f}s | nástroje: rag={sum(r['n_rag'] for r in ok)} web={sum(r['n_web'] for r in ok)} "
              f"pdf={sum(r['n_pdf'] for r in ok)}")
        for r in ok:
            picked = []
            if r["n_rag"]: picked.append(f"rag×{r['n_rag']}")
            if r["n_web"]: picked.append(f"web×{r['n_web']}")
            if r["n_pdf"]: picked.append(f"pdf×{r['n_pdf']}")
            print(f"  Q{r['qi']} [{r['dt']:.0f}s, {r['steps']} krok, {'+'.join(picked) or 'žiadny nástroj'}]")
    for r in results:
        if not r["ok"]:
            print(f"  Q{r['qi']} CHYBA: {r['err']}")
    if verbose:
        for r in ok:
            print(f"\n--- Q{r['qi']}: {r['q'][:70]}...\n{r['answer'][:900]}")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--concurrency", default="1")
    ap.add_argument("--verbose", action="store_true")
    a = ap.parse_args()
    print(f"V1={os.environ['V1_URL']}  RAG={os.environ['RAG_URL']}  MAX_STEPS={agent.MAX_STEPS}")
    for c in [int(x) for x in a.concurrency.split(",")]:
        run_level(c, a.verbose)
