#!/bin/bash
# (Re)build RAG indexu z $JH_RAG_DOCS do "${JH_RAG_INDEX}_v2" (živý index sa nedotkne).
# Beží NA CPU, NIKDY nie na login uzle — buď vo voľných jadrách bežiaceho jobu:
#     srun --overlap --jobid <JOBID> -w <MASTER> --ntasks=1 bash perun/build_index.sh
# alebo ako samostatný CPU job:
#     sbatch -A <ACCOUNT> --qos <QOS> -p cpu_short -c 64 -t 02:00:00 perun/build_index.sh
# Najprv `--dry-run` (len extrakcia + manifest, bez embeddingu):
#     ... bash perun/build_index.sh --dry-run
# Potom swap: mv rag_index rag_index_prev && mv rag_index_v2 rag_index
#             + reštart RAG (perun/rag_restart.sh) a agenta (perun/agent_restart.sh).
for CFG in "${JH_CONFIG:-}" "${SLURM_SUBMIT_DIR:-.}/config.env" "$(dirname "$0")/../config.env"; do
    [ -f "$CFG" ] && break
done
[ -f "$CFG" ] || { echo "config.env nenájdený (cp config.example.env config.env)"; exit 1; }
source "$CFG"

source "$JH_AGENT_VENV/bin/activate"
cd "$JH_REPO/agentic"
export OMP_NUM_THREADS=48
export HF_HUB_DISABLE_PROGRESS_BARS=1
export RAG_DOCS="$JH_RAG_DOCS"
export RAG_INDEX_DIR_V2="${JH_RAG_INDEX}_v2"
echo "=== BUILD start: $(date) na $(hostname) → $RAG_INDEX_DIR_V2 ==="
python rebuild_index.py "$@"
echo "=== BUILD koniec: $(date) ==="
