# 5. Prevádzka (cheatsheet)

Príkazy na klastri predpokladajú `cd ~/jankohrasko && source config.env`.

## Klaster

```bash
# stav jobu + master uzol (prvý v NODELIST)
squeue -u $USER -o '%i %j %T %M %l %N'

# nový štart celého stacku (~18 min boot, uzol sa ZMENÍ → potom reštart tunela na VM)
sbatch -A <ACC> --qos <QOS> perun/serve_agentic.sh
tail -f serve_agentic_<JOBID>.out

# reštart LEN agenta (model + RAG bežia ďalej, výpadok ~2 s)
nohup srun --overlap --jobid <JOBID> -w <MASTER> --ntasks=1 bash perun/agent_restart.sh <MASTER> &

# reštart RAG (napr. po reindexe) — potom aj agenta (načíta nový manifest)
nohup srun --overlap --jobid <JOBID> -w <MASTER> --ntasks=1 bash perun/rag_restart.sh &

# reindex (na CPU uzla, nie login) → ${JH_RAG_INDEX}_v2, potom swap — viď docs/03
srun --overlap --jobid <JOBID> -w <MASTER> --ntasks=1 bash perun/build_index.sh

# zdravie služieb (z uzla jobu)
curl -s http://<MASTER>:8000/health; curl -s http://<MASTER>:8100/health; curl -s http://<MASTER>:8200/health

# log otázok (osobné údaje!)
tail -f "$JH_QUERY_LOG"
```

Lokálny prístup bez frontendu (z vlastného PC):

```bash
ssh -N -o ServerAliveInterval=30 -o ServerAliveCountMax=3 -o ExitOnForwardFailure=yes \
    -L 8200:<MASTER>:8200 <USER>@<LOGIN_HOST>
# → http://localhost:8200
```

Job na `gpu_long` končí po 4 dňoch — treba nový `sbatch` (a reštart tunela). Ak `-w <MASTER>`
pri `srun --overlap` neprejde, použite `--relative=0` (prvý uzol alokácie = master).

## Frontend VM

```bash
az vm start      -g <RG> -n <VM>
az vm deallocate -g <RG> -n <VM>

# na VM
systemctl is-active pritunl-client janko-tunnel nginx
pritunl-client list                       # VPN Active?
curl -s http://127.0.0.1:8200/health      # agent cez tunel
sudo systemctl restart janko-tunnel       # po reštarte jobu (zmena uzla)
journalctl -u janko-tunnel -n 50
```

## Riešenie problémov

| Príznak | Príčina / riešenie |
|---|---|
| Web nič nevracia, `curl 127.0.0.1:8200` na VM zlyhá | tunel spadol alebo job beží na inom uzle → `systemctl restart janko-tunnel`; VPN `pritunl-client list` |
| Model „visí" s 0 % GPU po štarte | normálne — načítanie MoE váh a JIT; boot ~18 min (prvý štart dlhšie) |
| `cudaHostRegister with IoMemory failed error=800`, `DeepEP timeout (dispatch CPU)` | chýba `PeerMappingOverride=1` na uzle — [01](01_model_server.md#1-predpoklady-na-uzloch-admin) |
| `cuMemCreate ... NOT_PERMITTED` pri štarte DeepEP | chýba MNNVL patch alebo `SGLANG_DISABLE_MNNVL_FABRIC=1` |
| `memory capacity is unbalanced` | na niektorej GPU visí cudzí proces — nahlásiť správcom, bežať na zdravých uzloch |
| Odpoveď sa utne / HTTP 400 z modelu | pretečené okno; agent robí retry s `max_tokens=384`; znížte `AGENT_RESULT_CAP` |
| `web_search` nevracia nič | DuckDuckGo rate-limit — agent sám backoffuje (až 120 s) |
| Streamovaná odpoveď prichádza naraz | nginx bufferuje → `proxy_buffering off` |
| Pri záťažovom teste nové požiadavky timeoutujú | nie je chyba — fronta za 16 bežiacimi požiadavkami modelu |
