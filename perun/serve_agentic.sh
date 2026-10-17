#!/bin/bash
#SBATCH --partition=gpu_long
#SBATCH --nodes=2
#SBATCH --ntasks-per-node=1
#SBATCH --cpus-per-task=64
#SBATCH --gres=gpu:8
#SBATCH --time=4-00:00:00
#SBATCH --job-name=sglang_agentic
#SBATCH --output=serve_agentic_%j.out
#SBATCH --exclusive
#
# Spustenie (z koreňa repa; účet/QOS podľa vášho projektu):
#     sbatch -A <ACCOUNT> --qos <QOS> perun/serve_agentic.sh
#
# ★ CO-LOCATED AGENTIC — V1 (16× H200, deepep) + RAG service + agent orchestrátor v JEDNOM jobe.
# V1 beží na GPU (srun, 2 uzly). RAG/agent bežia na CPU MASTER uzla (128 jadier, 2.2 TB RAM,
# V1 z toho zožerie ~32 jadier → zvyšok voľný).
#
# Porty na MASTER uzle: V1=8000, RAG=8100, agent=8200.
# Pozn.: --job-name musí sedieť s JH_JOB_NAME v config.env (podľa neho tunel hľadá uzol).

set -uo pipefail

for CFG in "${JH_CONFIG:-}" "${SLURM_SUBMIT_DIR:-.}/config.env" "$(dirname "$0")/../config.env"; do
    [ -f "$CFG" ] && break
done
[ -f "$CFG" ] || { echo "config.env nenájdený (cp config.example.env config.env)"; exit 1; }
source "$CFG"

PORT=8000
TP=16
AGDIR="$JH_REPO/agentic"          # kód (rag_service.py, agent.py, ...)

export PATH="$JH_SGLANG_ENV/bin:$PATH"      # SGLang env priamo, bez `conda activate`

NODELIST=($(scontrol show hostnames "$SLURM_JOB_NODELIST"))
MASTER=${NODELIST[0]}
echo "=== AGENTIC: $(date) | uzly: ${NODELIST[*]} | master: $MASTER ==="

export JOB_CACHE="$JH_DATA/sglang_cache_${SLURM_JOB_ID}"
export MAX_JOBS=8
export SGLANG_DSV4_MHC_PREWARM=0
export PYTHONUNBUFFERED=1

# --- V1 IB/NVSHMEM/IBGDA (funkčná cesta A) ---
# Vyžaduje na GPU uzloch: nvidia_peermem, GDRCopy, NVreg_EnableStreamMemOPs=1 a
# NVreg_RegistryDwords="PeerMappingOverride=1;" (viď docs/01_model_server.md).
export NCCL_IB_HCA="$JH_IB_HCA"
export NVSHMEM_HCA_LIST="$JH_IB_HCA:1"
export NVSHMEM_DISABLE_IBGDA=0
export NVSHMEM_IB_ENABLE_IBGDA=1
export NVSHMEM_IBGDA_NIC_HANDLER=gpu
export NVSHMEM_DEBUG=WARN
SP=$("$JH_SGLANG_ENV/bin/python" -c 'import sysconfig; print(sysconfig.get_paths()["purelib"])')
export EP_SUPPRESS_NCCL_CHECK=1
export LD_LIBRARY_PATH=/usr/local/lib:$SP/nvidia/nvshmem/lib:${LD_LIBRARY_PATH:-}
export SGLANG_DISABLE_MNNVL_FABRIC=1        # potrebuje server/patch_sglang_mnnvl.py
export DEEP_EP_DISABLE_MNNVL_FABRIC=1

# ---------- 1. V1 server na pozadí (2 uzly, GPU) ----------
srun --kill-on-bad-exit=1 bash -c '
  export HOME='"$JOB_CACHE"'/node_$SLURM_NODEID
  mkdir -p "$HOME"
  export DG_JIT_CACHE_DIR='"$JH_DATA"'/dg_jit_cache_v1/node_$SLURM_NODEID
  mkdir -p "$DG_JIT_CACHE_DIR"
  export TRITON_CACHE_DIR=/tmp/triton_agentic_'"$SLURM_JOB_ID"'
  python -u -m sglang.launch_server \
      --model-path            '"$JH_MODEL_PATH"' \
      --tp-size               '"$TP"' --dp-size '"$TP"' --enable-dp-attention --ep-size '"$TP"' \
      --moe-a2a-backend       deepep \
      --nnodes 2 --node-rank $SLURM_NODEID --dist-init-addr '"$MASTER"':29500 \
      --trust-remote-code --host 0.0.0.0 --port '"$PORT"' \
      --chunked-prefill-size $((256 * '"$TP"')) --context-length 32768 \
      --mem-fraction-static 0.90 --cuda-graph-max-bs 8 \
      --watchdog-timeout 2400 --skip-server-warmup --disable-flashinfer-autotune \
      --tool-call-parser deepseekv4
' &
SRUN_PID=$!
echo "[agentic] V1 srun spustený (PID $SRUN_PID), čakám na health..."

# ---------- 2. RAG service + agent na CPU MASTER uzla ----------
# (beží na batch hoste = MASTER; zdieľa 128 jadier s V1 node-0, 2.2 TB RAM je takmer voľná)
if [ -d "$JH_AGENT_VENV" ]; then
    source "$JH_AGENT_VENV/bin/activate"
else
    echo "[agentic] VAROVANIE: $JH_AGENT_VENV neexistuje — spusti perun/setup_agentic_env.sh; preskakujem RAG/agent"
    wait $SRUN_PID; exit 0
fi

cd "$AGDIR"
export OMP_NUM_THREADS=48                        # bound CPU embedderu (uzol má 128 jadier)
export RAG_INDEX_DIR="$JH_RAG_INDEX"
export RAG_PORT=8100
export RAG_DEVICE=cpu
export PDF_DIR="$JH_AGENT_OUT"
export AGENT_QUERY_LOG="$JH_QUERY_LOG"
mkdir -p "$PDF_DIR"

# počkaj na V1 health (JIT prvého forwardu môže trvať — preto skip-warmup + tu dlhý timeout).
echo "[agentic] čakám na V1 na $MASTER:8000 ..."
for i in $(seq 1 180); do
    if curl -s -m 3 "http://$MASTER:8000/health" >/dev/null 2>&1; then echo "[agentic] V1 OK"; break; fi
    sleep 10
done

echo "[agentic] štartujem RAG service (port 8100)..."
python rag_service.py &
RAG_PID=$!
sleep 40   # RAG načíta index (~9 tis. chunkov) + embedder + BM25 (agent má aj manifest-retry)

export V1_URL="http://$MASTER:8000"
export RAG_URL="http://127.0.0.1:8100"
export AGENT_PORT=8200
echo "[agentic] štartujem agent orchestrátor (port 8200)..."
python agent.py --serve &
AGENT_PID=$!

echo "=== HOTOVO: V1=$MASTER:8000  RAG=$MASTER:8100  AGENT=$MASTER:8200 ==="
echo "    Test: curl -s http://$MASTER:8200/agent/chat -H 'Content-Type: application/json' -d '{\"message\":\"...\"}'"

# ---------- 3. čakaj na V1 (ak spadne, ukonči všetko) ----------
wait $SRUN_PID
echo "V1 skončil, ukončujem RAG/agent"
kill $RAG_PID $AGENT_PID 2>/dev/null || true
rm -rf "$JOB_CACHE"
