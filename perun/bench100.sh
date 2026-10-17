#!/bin/bash
# 100-užívateľský záťažový test agentickej vrstvy (RAG + web + fetch_url + PDF).
# Spúšťaj vo voľných jadrách bežiaceho jobu (nie na login uzle):
#     srun --overlap --jobid <JOBID> -w <MASTER> --ntasks=1 bash perun/bench100.sh <MASTER>
NODE="${1:?použitie: bench100.sh <master_uzol>}"
for CFG in "${JH_CONFIG:-}" "${SLURM_SUBMIT_DIR:-.}/config.env" "$(dirname "$0")/../config.env"; do
    [ -f "$CFG" ] && break
done
[ -f "$CFG" ] || { echo "config.env nenájdený (cp config.example.env config.env)"; exit 1; }
source "$CFG"

source "$JH_AGENT_VENV/bin/activate"
cd "$JH_REPO/agentic"
export V1_URL="http://${NODE}:8000"
export RAG_URL="http://${NODE}:8100"
export PDF_DIR="$JH_AGENT_OUT"
mkdir -p "$PDF_DIR"
echo "=== BENCH100 start: $(date) ==="
python tests/agent_bench.py --concurrency 100 2>"bench100_err_$(date +%s).log"
echo "=== BENCH100 koniec: $(date) ==="
echo "--- súbory vo výstupe ---"
ls -la "$PDF_DIR" | tail -20
