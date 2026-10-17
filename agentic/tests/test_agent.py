import sys, json, time, urllib.request

api = sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:8200"
questions = [
    "Aké témy a motívy prevládajú vo Válkovej poézii? Použi rag_search a cituj konkrétne verše.",
    "Kto bol Miroslav Válek a kedy sa narodil? Ak to nie je v dokumentoch, hľadaj na webe.",
]
for q in questions:
    print("\n" + "=" * 80)
    print("OTÁZKA:", q)
    body = json.dumps({"message": q}).encode()
    req = urllib.request.Request(api + "/agent/chat", data=body,
                                 headers={"Content-Type": "application/json"})
    t0 = time.time()
    try:
        r = urllib.request.urlopen(req, timeout=1200)
        j = json.loads(r.read())
        dt = time.time() - t0
        print(f"[{dt:.0f}s, krokov={j.get('steps')}]")
        print("--- NÁSTROJE ---")
        for t in j.get("trace", []):
            print(f"  · {t['tool']}({t['args']}) → {t['result_preview'][:90]}")
        print("--- ODPOVEĎ ---")
        print(j.get("answer", "")[:1200])
    except Exception as e:
        print("CHYBA:", repr(e))
