#!/bin/bash
# Jednorazové vytvorenie ČISTÉHO agentic venv (izolovaný, CPU torch) + stiahnutie MathJax.
# Pozn.: NEpoužívame --system-site-packages, lebo sglang env má torchcodec, ktorý padá na
# chýbajúcom FFmpeg (libavutil.so.56) a blokuje sentence-transformers. Čistý venv s CPU
# torchom je robustný a nezávislý. Embedder beží na CPU, takže GPU torch netreba.
#
# Ide len o pip install (sieť, žiadny výpočet) — dá sa spustiť na login uzle,
# ak to pravidlá klastra dovoľujú; inak cez krátky CPU job.
set -e

for CFG in "${JH_CONFIG:-}" "${SLURM_SUBMIT_DIR:-.}/config.env" "$(dirname "$0")/../config.env"; do
    [ -f "$CFG" ] && break
done
[ -f "$CFG" ] || { echo "config.env nenájdený (cp config.example.env config.env)"; exit 1; }
source "$CFG"

BASE_PY="$JH_SGLANG_ENV/bin/python"     # python 3.11 (akýkoľvek 3.11 stačí)
VENV="$JH_AGENT_VENV"

echo "=== čistý agentic venv v $VENV ==="
rm -rf "$VENV"
"$BASE_PY" -m venv "$VENV"
source "$VENV/bin/activate"
python -m pip install --upgrade pip

echo "=== CPU torch (malý, bez CUDA) ==="
python -m pip install torch==2.13.0 --index-url https://download.pytorch.org/whl/cpu

echo "=== agentic deps ==="
python -m pip install -r "$JH_REPO/agentic/requirements.txt"

echo "=== MathJax (lokálne, nie CDN) ==="
bash "$JH_REPO/perun/fetch_mathjax.sh"

echo "=== overenie ==="
python - <<'PY'
mods = {"faiss": "faiss-cpu", "sentence_transformers": "sentence-transformers",
        "rank_bm25": "rank_bm25", "fastapi": "fastapi", "uvicorn": "uvicorn",
        "multipart": "python-multipart", "ddgs": "ddgs", "bs4": "beautifulsoup4",
        "pypdf": "pypdf", "fitz": "pymupdf", "striprtf": "striprtf", "olefile": "olefile",
        "reportlab": "reportlab", "docx": "python-docx", "openpyxl": "openpyxl",
        "pptx": "python-pptx", "odf": "odfpy", "sympy": "sympy"}
bad = []
for m, name in mods.items():
    try:
        __import__(m)
    except Exception as e:
        bad.append(f"{name}: {e}")
print("CHYBY:\n  " + "\n  ".join(bad) if bad else "importy OK")
PY
echo "Embedder BAAI/bge-m3 (~2,3 GB) sa stiahne z HF pri prvom štarte rag_service.py."
echo "=== HOTOVO ==="
