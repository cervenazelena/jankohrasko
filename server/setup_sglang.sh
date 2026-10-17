#!/bin/bash
#SBATCH --partition=cpu_long
#SBATCH --nodes=1
#SBATCH --ntasks=1
#SBATCH --cpus-per-task=8
#SBATCH --time=02:00:00
#SBATCH --job-name=setup_sglang
#SBATCH --output=setup_sglang_%j.out
#
#     sbatch -A <ACCOUNT> --qos <QOS> server/setup_sglang.sh
#
# Python env so SGLang 0.5.14 + DeepEP pre DeepSeek-V4-Pro (H200 = sm_90, Hopper).
# Overené verzie z produkcie: server/sglang_env_packages.txt
#   sglang 0.5.14, torch 2.11.0 (CUDA 13.0), deep_ep 2.1.0, sgl_deep_gemm 0.1.3,
#   flashinfer-python 0.6.12, nvidia-nvshmem-cu13 3.4.5, nvidia-nccl-cu13 2.30.7, python 3.11.
#
# POZOR: conda create na Lustre môže visieť donekonečna — env vytvor na NVMe HOME
# (alebo použi `python3.11 -m venv`). Po inštalácii aplikuj server/patch_sglang_mnnvl.py.

set -euo pipefail

for CFG in "${JH_CONFIG:-}" "${SLURM_SUBMIT_DIR:-.}/config.env" "$(dirname "$0")/../config.env"; do
    [ -f "$CFG" ] && break
done
[ -f "$CFG" ] || { echo "config.env nenájdený (cp config.example.env config.env)"; exit 1; }
source "$CFG"

echo "=== SGLang inštalácia do $JH_SGLANG_ENV : $(date) ==="
if [ ! -x "$JH_SGLANG_ENV/bin/python" ]; then
    if command -v conda >/dev/null 2>&1; then
        conda create -p "$JH_SGLANG_ENV" python=3.11 -y
    else
        python3.11 -m venv "$JH_SGLANG_ENV"
    fi
fi
PY="$JH_SGLANG_ENV/bin/python"
"$PY" -m pip install --upgrade pip

# SGLang z PyPI (torch, sgl-kernel, flashinfer, sgl_deep_gemm prídu ako závislosti).
# DeepEP sa kompiluje zo zdrojákov zvlášť: server/build_deepep.sh.
# Výsledok porovnaj so server/sglang_env_packages.txt (presný stav produkčného env) —
# ak pip vyrieši iné verzie (napr. torch inej CUDA), doinštaluj ich podľa toho zoznamu.
"$PY" -m pip install "sglang[all]==0.5.14"

echo "=== nainštalované verzie ==="
"$PY" -m pip show sglang torch deep_ep sgl_deep_gemm flashinfer-python 2>/dev/null | grep -E "^(Name|Version):"
"$PY" -c "import torch; print('torch', torch.__version__, 'CUDA', torch.version.cuda)"
"$PY" -c "import sglang; print('sglang', sglang.__version__)"

echo "=== MNNVL patch (dry-run; aplikuj s --apply) ==="
"$PY" "$JH_REPO/server/patch_sglang_mnnvl.py" || true
echo "=== koniec: $(date) ==="
