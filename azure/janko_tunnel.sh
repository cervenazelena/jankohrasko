#!/bin/bash
# ~/janko_tunnel.sh na frontend VM — spúšťa ho janko-tunnel.service.
# 1) cez login uzol zistí AKTUÁLNY master uzol jobu (forced command agent_node.sh;
#    obmedzený kľúč nevie spustiť nič iné, preto stačí `ssh perun-login true`),
# 2) otvorí forward-only tunel 127.0.0.1:8200 → <uzol>:8200.
# Pri reštarte jobu sa uzol mení → `sudo systemctl restart janko-tunnel`.
set -euo pipefail

NODE=$(ssh -o BatchMode=yes -o ConnectTimeout=20 perun-login true | tr -d '[:space:]')
if [[ ! "$NODE" =~ ^[A-Za-z0-9.-]+$ ]]; then
    echo "janko-tunnel: neplatný/prázdny uzol '${NODE}' (beží job?)" >&2
    exit 1                                  # systemd to skúsi znova (RestartSec)
fi
echo "janko-tunnel: master uzol = $NODE"

export AUTOSSH_GATETIME=0
exec autossh -M 0 -N \
    -o ServerAliveInterval=15 -o ServerAliveCountMax=3 -o TCPKeepAlive=yes \
    -o ExitOnForwardFailure=yes \
    -L "127.0.0.1:8200:${NODE}:8200" perun-login
