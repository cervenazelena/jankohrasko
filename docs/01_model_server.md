# 1. Model server — DeepSeek-V4-Pro na 2 uzloch

Model **DeepSeek-V4-Pro-FP8** (`DeepseekV4ForCausalLM`, MoE, MTP hlava
`num_nextn_predict_layers=1`) servírovaný cez **SGLang 0.5.14** na **2 uzloch × 8× H200 141 GB**
prepojených **InfiniBand** (bez NVLink medzi uzlami). Paralelizmus TP=16 / DP=16 (DP-attention) /
EP=16, all-to-all experty cez **DeepEP V1 (NVSHMEM/IBGDA)** — „cesta A".

Referenčný hardvér (TUKE Perun): GPU uzol = 2 sockety × 64 jadier = 128 CPU jadier, ~2,2 TB RAM,
8× H200, 4× HCA mlx5 (používa sa jedna). FP8 váhy ≈ 124 GB na GPU.

## 1. Predpoklady na uzloch (admin)

DeepEP cez IBGDA zvoní na doorbell sieťovej karty priamo z GPU. Na to musia správcovia
na **všetkých GPU uzloch** zabezpečiť:

| Čo | Prečo | Overenie |
|---|---|---|
| modul `nvidia_peermem` | GPUDirect RDMA dátová cesta | `lsmod \| grep nvidia_peermem` |
| **GDRCopy** (gdrdrv + `/dev/gdrdrv` + `libgdrapi` v `/usr/local/lib`; použité v2.4.4) | NVSHMEM/IBGDA | `server/diag_gdrcopy.sh` (`gdrcopy_sanity`) |
| `options nvidia NVreg_EnableStreamMemOPs=1 NVreg_RegistryDwords="PeerMappingOverride=1;"` + `dracut -f` + reload modulu/reboot | `cudaHostRegister(IoMemory)` mapuje BAR NIC do GPU; bez toho `error=800 NOT_PERMITTED` a `DeepEP error: timeout (dispatch CPU)` | `cat /proc/driver/nvidia/params \| grep -E 'RegistryDwords\|StreamMemOPs'` |

Pozor: prvá inštalácia GDRCopy na TUKE bola neúplná (0-bajtový `libgdrapi`, chýbal
`/dev/gdrdrv`) — overte pred behom. Ak je modul `nvidia` v initramfs, samotná zmena
`/etc/modprobe.d/nvidia.conf` nestačí — treba `dracut -f`. Text žiadosti, ktorý prešiel
u správcov: [server/ADMIN_REQUEST_deepep.md](../server/ADMIN_REQUEST_deepep.md).

## 2. Konfigurácia

```bash
git clone https://github.com/cervenazelena/jankohrasko.git ~/jankohrasko
cd ~/jankohrasko
cp config.example.env config.env      # uprav JH_DATA, JH_SGLANG_ENV, ...
```

Všetky skripty v `server/` a `perun/` načítajú `config.env` (z adresára, odkiaľ ich spúšťate,
alebo z `JH_CONFIG`). Účet a QOS SLURM-u sa zadávajú pri odoslaní: `sbatch -A <ACCOUNT> --qos <QOS> ...`.

## 3. SGLang prostredie

```bash
sbatch -A <ACC> --qos <QOS> server/setup_sglang.sh     # python 3.11 + sglang[all]==0.5.14
"$JH_SGLANG_ENV/bin/python" server/patch_sglang_mnnvl.py --apply
sbatch -A <ACC> --qos <QOS> server/build_deepep.sh     # DeepEP @099d5f2 zo zdrojákov
```

Produkčné verzie: `sglang 0.5.14`, `torch 2.11.0` (CUDA 13.0), `deep_ep 2.1.0+099d5f2`,
`sgl_deep_gemm 0.1.3`, `flashinfer-python 0.6.12`, `nvidia-nvshmem-cu13 3.4.5`,
`nvidia-nccl-cu13 2.30.7`. Celý zoznam: [server/sglang_env_packages.txt](../server/sglang_env_packages.txt).

- **conda na Lustre môže visieť** pri `conda create` — env vytvorte na NVMe HOME, alebo `python3.11 -m venv`.
- Skripty volajú priamo `$JH_SGLANG_ENV/bin/python` (bez `conda activate`) — funguje aj s condou,
  ktorej absolútne cesty sa pokazili presunom úložiska.

### MNNVL patch (nutný)
H200 falošne hlási podporu multi-node NVLink fabric → SGLang posiela `allow_mnnvl=True` do
`deep_ep.Buffer` (v deep_ep 2.1.0 = C++ `use_fabric`) → `cuMemCreate(FABRIC)` → `NOT_PERMITTED`.
[server/patch_sglang_mnnvl.py](../server/patch_sglang_mnnvl.py) zmení v
`sglang/srt/layers/moe/token_dispatcher/deepep.py` natvrdo `allow_mnnvl=True` na prepínač
`SGLANG_DISABLE_MNNVL_FABRIC=1` (nastavuje ho `perun/serve_agentic.sh`). C++ rebuild netreba.
`DEEP_EP_DISABLE_MNNVL_FABRIC=1` v serve skripte je pozostatok staršieho C++ pokusu — neškodí.

## 4. Model

```bash
sbatch -A <ACC> --qos <QOS> server/download_model.sh   # sgl-project/DeepSeek-V4-Pro-FP8, ~1607 GB
```
FP8 checkpoint má **prázdny `chat_template`** — SGLang dodá vlastný DeepSeek template.

## 5. Test DeepEP medzi uzlami

```bash
sbatch -A <ACC> --qos <QOS> server/test_deepep_internode.sh   # ~2 min, BEZ SGLang
```
Izolovaný `tests/legacy/test_internode.py` z DeepEP. Úspech = žiadne `num_recv_tokens: -1`,
žiadny `cudaHostRegister with IoMemory failed`. Spúšťajte po každom zásahu správcov,
pred plným serverom (ten bootuje ~18 min).

## 6. Spustenie

Model sa spúšťa spolu s RAG a agentom jedným jobom (agent: [02_agent.md](02_agent.md)):

```bash
sbatch -A <ACC> --qos <QOS> perun/serve_agentic.sh
tail -f serve_agentic_<JOBID>.out       # "=== HOTOVO: V1=gpuXX:8000 ..."
```

Kľúčové prostredie ([perun/serve_agentic.sh](../perun/serve_agentic.sh)):

```bash
export NCCL_IB_HCA=mlx5_0
export NVSHMEM_HCA_LIST=mlx5_0:1          # single-rail (multi-rail padal: 719 dispatch fault)
export NVSHMEM_IB_ENABLE_IBGDA=1
export NVSHMEM_IBGDA_NIC_HANDLER=gpu      # GPU-side doorbell → dá sa zachytiť CUDA graf
export SGLANG_DISABLE_MNNVL_FABRIC=1
export LD_LIBRARY_PATH=/usr/local/lib:$SP/nvidia/nvshmem/lib:$LD_LIBRARY_PATH   # GDRCopy + NVSHMEM
```

```bash
python -m sglang.launch_server --model-path $JH_MODEL_PATH \
  --tp-size 16 --dp-size 16 --enable-dp-attention --ep-size 16 \
  --moe-a2a-backend deepep \
  --nnodes 2 --node-rank $SLURM_NODEID --dist-init-addr $MASTER:29500 \
  --trust-remote-code --host 0.0.0.0 --port 8000 \
  --chunked-prefill-size 4096 --context-length 32768 \
  --mem-fraction-static 0.90 --cuda-graph-max-bs 8 \
  --watchdog-timeout 2400 --skip-server-warmup --disable-flashinfer-autotune \
  --tool-call-parser deepseekv4
```

- `--tool-call-parser deepseekv4` — DeepSeekV4Detector (DSML/XML formát, paralelné tool-cally).
- `--watchdog-timeout 2400` + `--skip-server-warmup` — prvý forward kompiluje DeepGEMM JIT
  dlhšie, než povoľujú predvolené timeouty. DeepGEMM cache je perzistentná
  (`$JH_DATA/dg_jit_cache_v1`), ďalšie štarty sú rýchlejšie.
- **Boot ~18 min.** 0 % využitie GPU počas načítania MoE váh je normálne — nie je to zaseknutie.
- `--mem-fraction-static 0.90` a SGLang predvolené `max_running_requests=16` sú stabilný
  „sweet spot". Viac súbežných požiadaviek (48/64) → OOM pri zachytávaní CUDA grafu.

## Výkon (namerané, `server/bench_concurrency.py`)

| Záťaž | Výsledok |
|---|---|
| 1 používateľ | 19,6–21 tok/s, KV cache 224 256 tokenov |
| 100 súbežných | 17 tok/s/používateľ, **1535 tok/s spolu**, TTFT 0,7 s, 100/100 OK |
| 200 súbežných | 10,5 tok/s/používateľ, 1899 tok/s spolu (strop), TTFT 1,2 s |

## Čo sme skúšali a nefungovalo / alternatívy

| Variant | Výsledok |
|---|---|
| **1 uzol, FP4 checkpoint, MoE runner `marlin`, TP=8** | funguje, ~75 tok/s pre 1 používateľa, ale malá KV cache → rýchlosť áno, súbežnosť nie |
| **Cesta B — DeepEP V2 (NCCL Gin, SGLang PR #29525, `--moe-a2a-backend deepep_v2`)** | funguje bez `PeerMappingOverride`, KV 405k, ale eager 5,5 tok/s; s CUDA grafom (len bs=1) 12,6 tok/s a 670 tok/s pri 100 používateľoch → V1 dominuje |
| CPU-assisted IBGDA (`NVSHMEM_IBGDA_NIC_HANDLER=cpu`) | inicializuje sa, ale dispatch zamrzne; s CUDA grafom `700 ILLEGAL_ADDRESS` |
| Multi-rail IB (bez `NVSHMEM_HCA_LIST`) | `719 dispatch fault` |
| Špekulatívne dekódovanie (EAGLE/MTP) na 2 uzloch | draft sa načíta, ale CUDA graf `719 LAUNCH_FAILED`, eager `DeepEP timeout` na prvom requeste |

## SLURM pravidlá (TUKE Perun, 2026)

- Partícia `gpu_long`: max **4 dni** (nedá sa predĺžiť → resubmit). `gpu_short`: 2 dni.
- Limit na používateľa v „long" partíciách: **2 uzly** — iné bežiace joby môžu blokovať nový 2-uzlový job.
- `--nodelist`/`-w` pri `sbatch` plánovač ignoruje — uzol sa pri každom štarte **mení**
  (preto tunel zisťuje uzol dynamicky, viď [04](04_frontend_azure.md)).
