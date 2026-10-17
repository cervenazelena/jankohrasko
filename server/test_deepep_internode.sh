#!/bin/bash
#SBATCH --partition=gpu_long
#SBATCH --nodes=2
#SBATCH --ntasks-per-node=1
#SBATCH --cpus-per-task=32
#SBATCH --gres=gpu:8
#SBATCH --time=0-00:20:00
#SBATCH --job-name=test_deepep_in
#SBATCH --output=test_deepep_internode_%j.out
#SBATCH --exclusive
#
#     sbatch -A <ACCOUNT> --qos <QOS> server/test_deepep_internode.sh
#     NIC_HANDLER=cpu sbatch ...      # CPU-assisted IBGDA (na TUKE zamŕzal dispatch)
#
# Izolovaný test DeepEP internode dispatch (BEZ SGLang/DeepGEMM) — zistí, či je problém
# v DeepEP/NVSHMEM/IB vrstve alebo v SGLang. ~2 min; spusti PRED plným serverom
# (napr. po admin zásahu PeerMappingOverride=1). Potrebuje zdrojáky DeepEP (tests/legacy).

set -uo pipefail

for CFG in "${JH_CONFIG:-}" "${SLURM_SUBMIT_DIR:-.}/config.env" "$(dirname "$0")/../config.env"; do
    [ -f "$CFG" ] && break
done
[ -f "$CFG" ] || { echo "config.env nenájdený (cp config.example.env config.env)"; exit 1; }
source "$CFG"

export PATH="$JH_SGLANG_ENV/bin:$PATH"
SP=$(python -c 'import sysconfig; print(sysconfig.get_paths()["purelib"])')
DEEPEP="$JH_DEEPEP_SRC"

NODELIST=($(scontrol show hostnames "$SLURM_JOB_NODELIST"))
MASTER=${NODELIST[0]}
echo "=== DeepEP internode test: $(date) | uzly: ${NODELIST[*]} | master: $MASTER ==="

# Rovnaké NVSHMEM/GDRCopy/IB prostredie ako perun/serve_agentic.sh
export NCCL_IB_HCA="$JH_IB_HCA"
export NVSHMEM_HCA_LIST="$JH_IB_HCA:1"
export NVSHMEM_IB_ENABLE_IBGDA=1
export NVSHMEM_DISABLE_IBGDA=0
export NVSHMEM_IBGDA_NIC_HANDLER=${NIC_HANDLER:-gpu}
export NVSHMEM_DEBUG=${NVSHMEM_DBG:-WARN}
[ -n "${NVSHMEM_SUBSYS:-}" ] && export NVSHMEM_DEBUG_SUBSYS=$NVSHMEM_SUBSYS
export EP_SUPPRESS_NCCL_CHECK=1
export LD_LIBRARY_PATH=/usr/local/lib:$SP/nvidia/nvshmem/lib:${LD_LIBRARY_PATH:-}
export PYTHONUNBUFFERED=1

echo "NIC_HANDLER=$NVSHMEM_IBGDA_NIC_HANDLER"

srun --kill-on-bad-exit=1 bash -c '
  export MASTER_ADDR='"$MASTER"'
  export MASTER_PORT=18361
  export WORLD_SIZE=2
  export RANK=$SLURM_NODEID
  export HOME=/tmp/deepep_test_'"$SLURM_JOB_ID"'_$SLURM_NODEID
  mkdir -p "$HOME"
  echo "[node $SLURM_NODEID / $(hostname)] RANK=$RANK WORLD_SIZE=$WORLD_SIZE MASTER=$MASTER_ADDR"
  cd '"$DEEPEP"'
  # num_tokens malé (rýchly test), 256 expertov / 16 rankov = 16 local expertov
  python tests/legacy/test_internode.py --num-tokens 512 --num-experts 256
'

echo "=== test skončil: $(date) ==="
