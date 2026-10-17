"""SSRF test nástroja fetch_url — interné adresy musia byť zablokované, verejné povolené.

    cd agentic && python tests/test_ssrf.py [interný_uzol]
"""
import os, sys
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
import tools

node = sys.argv[1] if len(sys.argv) > 1 else "localhost"
tests = [
    ("privátna IP",       "http://10.0.0.1/"),
    ("cloud metadata",    "http://169.254.169.254/latest/meta-data/"),
    ("localhost agent",   "http://127.0.0.1:8200/health"),
    ("interný uzol V1",   f"http://{node}:8000/v1/models"),
    ("externé (OK)",      "https://example.com/"),
]
for name, url in tests:
    r = tools.exec_fetch_url(url, max_chars=80)
    verdict = "ZABLOKOVANÉ" if r.startswith("Zamietnut") else ("chyba" if "chyba" in r[:20] else "POVOLENÉ")
    print(f"  [{verdict:11}] {name:18} {url}")
    print(f"       -> {r[:90].replace(chr(10), ' ')}")
