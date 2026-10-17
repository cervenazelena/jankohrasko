#!/bin/bash
# Reštart RAG služby (port 8100) v popredí — perzistentný srun step na MASTER uzle:
#     nohup srun --overlap --jobid <JOBID> -w <MASTER> --ntasks=1 bash perun/rag_restart.sh &
# Po reštarte RAG reštartuj aj agenta (perun/agent_restart.sh), aby si načítal nový manifest.
for CFG in "${JH_CONFIG:-}" "${SLURM_SUBMIT_DIR:-.}/config.env" "$(dirname "$0")/../config.env"; do
    [ -f "$CFG" ] && break
done
[ -f "$CFG" ] || { echo "config.env nenájdený (cp config.example.env config.env)"; exit 1; }
source "$CFG"

pkill -f "rag_service.py" && echo "starý RAG zabitý" || echo "RAG nebežal"
sleep 2
source "$JH_AGENT_VENV/bin/activate"
cd "$JH_REPO/agentic"
export OMP_NUM_THREADS=48
export RAG_INDEX_DIR="$JH_RAG_INDEX"
export RAG_PORT=8100
export RAG_DEVICE=cpu
exec python rag_service.py
