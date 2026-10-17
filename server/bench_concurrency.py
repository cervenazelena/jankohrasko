"""Concurrency benchmark pre SGLang server — meria SKUTOČNÚ priepustnosť pri záťaži.

Vystrelí N súbežných chat-completion streamov naraz, meria:
  - per-user tok/s (p50 / p95)  — čo cíti jeden používateľ
  - agregát tok/s               — celkový výkon servera
  - TTFT (time-to-first-token)  — latencia odozvy

Použitie:
    python bench_concurrency.py --api http://<uzol>:8000 --concurrency 1,8,32,64,128 \
        --max-tokens 200 --prompt-tokens 512

Odporúčanie: spusti pre viac hodnôt concurrency naraz (čiarkou) → dostaneš škálovaciu krivku.
"""
import argparse, json, time, statistics, sys, threading
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed

PROMPT_BASE = (
    "Si expertný asistent. Podrobne a súvislo vysvetli nasledujúcu tému, "
    "uveď kontext, príklady a záver. Téma: "
)
TOPICS = [
    "história Bratislavy od stredoveku po súčasnosť",
    "ako funguje jadrová elektráreň a aké sú jej riziká",
    "vývoj slovenského jazyka a Štúrova kodifikácia",
    "princípy strojového učenia a neurónových sietí",
    "klimatické zmeny a ich dopad na strednú Európu",
    "dejiny Rímskej ríše a príčiny jej pádu",
    "ako sa tvorí počasie a čo ovplyvňuje tlakové níže",
    "základy kvantovej mechaniky pre laika",
]


def one_request(api, model, topic, max_tokens, temperature, timeout):
    body = json.dumps({
        "model": model,
        "messages": [{"role": "user", "content": PROMPT_BASE + topic}],
        "max_tokens": max_tokens, "temperature": temperature, "stream": True,
    }).encode()
    req = urllib.request.Request(api + "/v1/chat/completions", data=body,
                                 headers={"Content-Type": "application/json"})
    t0 = time.time(); ttft = None; ntok = 0
    try:
        r = urllib.request.urlopen(req, timeout=timeout)
        for raw in r:
            line = raw.decode("utf-8", "ignore").strip()
            if not line.startswith("data:"):
                continue
            data = line[5:].strip()
            if data == "[DONE]":
                break
            try:
                j = json.loads(data)
                delta = j["choices"][0].get("delta", {}).get("content")
                if delta:
                    if ttft is None:
                        ttft = time.time() - t0
                    ntok += 1
            except Exception:
                pass
        dt = time.time() - t0
        # decode tok/s = tokeny po prvom / (čas - ttft)
        gen_time = max(dt - (ttft or 0), 1e-6)
        return {"ok": True, "ntok": ntok, "dt": dt, "ttft": ttft or dt,
                "tok_s": ntok / gen_time if ntok else 0.0}
    except Exception as e:
        return {"ok": False, "err": repr(e), "dt": time.time() - t0}


def run_level(api, model, conc, args):
    topics = [TOPICS[i % len(TOPICS)] for i in range(conc)]
    wall0 = time.time()
    results = []
    with ThreadPoolExecutor(max_workers=conc) as ex:
        futs = [ex.submit(one_request, api, model, t, args.max_tokens,
                          args.temperature, args.timeout) for t in topics]
        for f in as_completed(futs):
            results.append(f.result())
    wall = time.time() - wall0
    ok = [r for r in results if r["ok"]]
    fail = [r for r in results if not r["ok"]]
    if not ok:
        print(f"  concurrency={conc}: VŠETKY ZLYHALI ({len(fail)}), napr. {fail[0]['err'] if fail else ''}")
        return
    tps = sorted(r["tok_s"] for r in ok)
    ttfts = sorted(r["ttft"] for r in ok)
    total_tok = sum(r["ntok"] for r in ok)
    def pct(xs, p): return xs[min(len(xs)-1, int(len(xs)*p))]
    print(f"  concurrency={conc:<4} | ok={len(ok)}/{conc} | "
          f"per-user tok/s p50={pct(tps,0.5):.1f} p95={pct(tps,0.95):.1f} | "
          f"AGREGÁT={total_tok/wall:.0f} tok/s | "
          f"TTFT p50={pct(ttfts,0.5):.1f}s p95={pct(ttfts,0.95):.1f}s | wall={wall:.1f}s")


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--api", required=True)
    p.add_argument("--concurrency", default="1,8,32,64,128")
    p.add_argument("--max-tokens", type=int, default=200)
    p.add_argument("--temperature", type=float, default=0.7)
    p.add_argument("--timeout", type=int, default=900)
    args = p.parse_args()
    api = args.api.rstrip("/")
    # model name
    try:
        r = urllib.request.urlopen(api + "/v1/models", timeout=15)
        model = json.loads(r.read())["data"][0]["id"]
    except Exception:
        model = "x"
    print(f"API: {api} | model: {model} | max_tokens={args.max_tokens}")
    print("=" * 100)
    for c in [int(x) for x in args.concurrency.split(",")]:
        run_level(api, model, c, args)
    print("=" * 100)


if __name__ == "__main__":
    main()
