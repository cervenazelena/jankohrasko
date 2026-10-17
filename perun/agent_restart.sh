#!/bin/bash
# Reštart LEN agenta (port 8200) — model V1 aj RAG bežia ďalej, výpadok ~2 s.
# Spúšťa sa ako perzistentný srun step v bežiacom jobe na MASTER uzle:
#     nohup srun --overlap --jobid <JOBID> -w <MASTER> --ntasks=1 bash perun/agent_restart.sh <MASTER> &
# (obyčajný nohup vnútri krátkeho srun kroku SLURM pri cleanupe cgroup zabije)
NODE="${1:?použitie: agent_restart.sh <master_uzol>}"

for CFG in "${JH_CONFIG:-}" "${SLURM_SUBMIT_DIR:-.}/config.env" "$(dirname "$0")/../config.env"; do
    [ -f "$CFG" ] && break
done
[ -f "$CFG" ] || { echo "config.env nenájdený (cp config.example.env config.env)"; exit 1; }
source "$CFG"

fuser -k 8200/tcp 2>/dev/null
pkill -9 -f "agent.py --serve" 2>/dev/null
sleep 3
source "$JH_AGENT_VENV/bin/activate"
cd "$JH_REPO/agentic"
export V1_URL="http://${NODE}:8000"
export RAG_URL=http://127.0.0.1:8100
export PDF_DIR="$JH_AGENT_OUT"
export AGENT_QUERY_LOG="$JH_QUERY_LOG"
export AGENT_PORT=8200
exec python agent.py --serve
