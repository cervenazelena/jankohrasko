#!/bin/bash
#SBATCH --partition=gpu_long
#SBATCH --nodes=1
#SBATCH --ntasks=1
#SBATCH --cpus-per-task=32
#SBATCH --gres=gpu:1
#SBATCH --time=0-01:00:00
#SBATCH --job-name=build_deepep
#SBATCH --output=build_deepep_%j.out
#
#     sbatch -A <ACCOUNT> --qos <QOS> server/build_deepep.sh
#
# Kompilácia DeepEP zo zdrojákov do SGLang env — tak, ako beží v produkcii:
#   deepseek-ai/DeepEP @ 099d5f2 (deep_ep 2.1.0+099d5f2), CUDA 13 z pip balíkov env,
#   + Hopper patch st.bulk (patches/deepep_ptx_stbulk_hopper.patch; nutný len pre
#   DeepEP V2/ElasticBuffer, pre V1 cestu neškodí).
# 1 GPU kvôli libcuda linkage; samotná kompilácia je CPU.

set -euo pipefail

for CFG in "${JH_CONFIG:-}" "${SLURM_SUBMIT_DIR:-.}/config.env" "$(dirname "$0")/../config.env"; do
    [ -f "$CFG" ] && break
done
[ -f "$CFG" ] || { echo "config.env nenájdený (cp config.example.env config.env)"; exit 1; }
source "$CFG"

DEEPEP_COMMIT=099d5f2bad488b9c534ea785062b12f2e91d1d41
export PATH="$JH_SGLANG_ENV/bin:$PATH"
SP=$(python -c 'import sysconfig; print(sysconfig.get_paths()["purelib"])')

if [ ! -d "$JH_DEEPEP_SRC/.git" ]; then
    git clone https://github.com/deepseek-ai/DeepEP.git "$JH_DEEPEP_SRC"
fi
cd "$JH_DEEPEP_SRC"
git checkout "$DEEPEP_COMMIT"
if ! grep -q "PATCH(TUKE)" deep_ep/include/deep_ep/common/ptx.cuh; then
    git apply "$JH_REPO/server/patches/deepep_ptx_stbulk_hopper.patch"
fi

# Build prostredie: CUDA 13 toolchain z pip balíkov env
export CUDA_HOME=$SP/nvidia/cu13
export PATH=$CUDA_HOME/bin:$PATH
export LIBRARY_PATH=$SP/nvidia/cudart/lib:$SP/nvidia/nccl/lib:$SP/nvidia/nvshmem/lib:${LIBRARY_PATH:-}
export LD_LIBRARY_PATH=$SP/nvidia/cudart/lib:$SP/nvidia/nccl/lib:$SP/nvidia/nvshmem/lib:${LD_LIBRARY_PATH:-}

# Symlinky pre linker: libcudart.so + stub libcuda.so
LINK_DIR=/tmp/deepep_links_$$
mkdir -p "$LINK_DIR"
ln -sf "$SP/nvidia/cudart/lib/libcudart.so.13" "$LINK_DIR/libcudart.so"
STUB=$(ls /opt/nvidia/hpc_sdk/Linux_x86_64/*/cuda/lib*/stubs/libcuda.so 2>/dev/null | head -1 || true)
[ -z "$STUB" ] && STUB=$(find /usr/local/cuda* -path '*stubs/libcuda.so' 2>/dev/null | head -1 || true)
[ -n "$STUB" ] && ln -sf "$STUB" "$LINK_DIR/libcuda.so"
export LIBRARY_PATH=$LINK_DIR:$LIBRARY_PATH

echo "CUDA_HOME: $CUDA_HOME | nvcc: $(nvcc --version 2>&1 | grep release | head -1)"
rm -rf build/ dist/ deep_ep.egg-info/
export MAX_JOBS=8            # každý nvcc ~4 GB RAM
pip install . --no-build-isolation -v

cd /tmp && python -c "import deep_ep; print('deep_ep OK', deep_ep.Buffer)"
rm -rf "$LINK_DIR"
echo "=== HOTOVO: $(date) ==="
