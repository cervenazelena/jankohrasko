"""Ukáž plné odpovede + trace na otázky s AKTUÁLNYMI faktami (web) — overenie faktickosti."""
import os, sys
os.environ.setdefault("V1_URL", "http://127.0.0.1:8000")
os.environ.setdefault("RAG_URL", "http://127.0.0.1:8100")
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
import agent

QS = [
    "Válek zastával najvyššiu štátnu funkciu v oblasti kultúry. Akú funkciu to bola a kto ju "
    "vykonáva v aktuálnej vláde Slovenskej republiky?",
    "Ktorý slávny Válkov verš sa začína slovami „Ospravedlňte poruchu“ a kto je v súčasnosti "
    "primátorom mesta, kde sa Válek narodil?",
    "V ktorej Válkovej zbierke sa objavuje motív nepokoja a otázka „kde som?“, a ktoré slovenské "
    "literárne ocenenie za pôvodnú prózu (Anasoft litera) bolo udelené naposledy a komu?",
]
for i, q in enumerate(QS):
    print("\n" + "=" * 90)
    print("OTÁZKA:", q)
    out = agent.run_agent(q)
    print(f"[krokov={out['steps']}]")
    for t in out.get("trace", []):
        a = {k: str(v)[:50] for k, v in t["args"].items()}
        print(f"  · {t['tool']}({a})")
    print("--- ODPOVEĎ ---")
    print(out.get("answer", ""))
