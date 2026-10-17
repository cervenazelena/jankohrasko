"""Priamy test tool-call slučky (obíde FastAPI endpoint). V1/RAG cez env pred importom."""
import os, sys
os.environ.setdefault("V1_URL", "http://127.0.0.1:8000")
os.environ.setdefault("RAG_URL", "http://127.0.0.1:8100")
os.environ.setdefault("PDF_DIR", "./agent_out")

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
import agent

qs = [
    "Aké témy a motívy prevládajú vo Válkovej poézii? Použi rag_search a cituj konkrétne verše.",
    "Kto bol Miroslav Válek a kedy sa narodil? Ak to nie je v lokálnych dokumentoch, hľadaj na webe.",
]
for q in qs:
    print("\n" + "=" * 80)
    print("OTÁZKA:", q)
    out = agent.run_agent(q)
    print(f"[krokov={out['steps']}]")
    print("--- NÁSTROJE ---")
    for t in out.get("trace", []):
        print(f"  · {t['tool']}({t['args']}) → {t['result_preview'][:90]}")
    print("--- ODPOVEĎ ---")
    print(out.get("answer", "")[:1500])
