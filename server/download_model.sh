#!/bin/bash
#SBATCH --partition=cpu_long
#SBATCH --nodes=1
#SBATCH --ntasks=1
#SBATCH --cpus-per-task=16
#SBATCH --time=2-00:00:00
#SBATCH --job-name=stiahni_fp8
#SBATCH --output=stiahni_fp8_%j.out
#
#     sbatch -A <ACCOUNT> --qos <QOS> server/download_model.sh
#
# Stiahne FP8 checkpoint DeepSeek-V4-Pro (~1607 GB) pre 2-uzlový deepep serving
# (Hopper-natívne FP8 kernely, ~124 GB váh na GPU pri TP=16). Compute uzly na TUKE
# Perun majú priamy internet; ak váš klaster nie, sťahujte cez dátový/login uzol.

set -euo pipefail

for CFG in "${JH_CONFIG:-}" "${SLURM_SUBMIT_DIR:-.}/config.env" "$(dirname "$0")/../config.env"; do
    [ -f "$CFG" ] && break
done
[ -f "$CFG" ] || { echo "config.env nenájdený (cp config.example.env config.env)"; exit 1; }
source "$CFG"

REPO=sgl-project/DeepSeek-V4-Pro-FP8
DEST="$JH_MODEL_PATH"
PY="$JH_SGLANG_ENV/bin/python"

export HF_HUB_ENABLE_HF_TRANSFER=1   # rýchly downloader (ak je hf_transfer nainštalovaný)
export HF_HUB_DOWNLOAD_TIMEOUT=60

echo "=== stiahni $REPO → $DEST : $(date) ==="
mkdir -p "$DEST"

"$PY" - <<PY
from huggingface_hub import snapshot_download
p = snapshot_download(repo_id="$REPO", local_dir="$DEST", max_workers=16)
print("HOTOVO:", p)
PY

echo "=== veľkosť po stiahnutí ==="
du -sh "$DEST"
echo "=== safetensors počet ==="
ls "$DEST"/*.safetensors 2>/dev/null | wc -l
echo "=== koniec: $(date) ==="
