# 4. Verejný frontend na Azure

Compute uzly klastra nie sú z internetu dostupné a ani VPN klastra nepustí ďalej než na
login uzly. Preto: malý verejný VM → VPN do siete klastra → SSH tunel cez login uzol na
master uzol jobu → nginx ho vystaví na porte 80.

```
internet → nginx :80 (VM) → 127.0.0.1:8200 ─autossh─► login uzol ─► <master>:8200 (agent)
                                    └── cez Pritunl VPN klastra
```

## VM

Referenčné nasadenie: Ubuntu 22.04, **Standard_D2s_v3** (2 vCPU / 8 GB), disk 30 GB, región
**polandcentral** (najbližšie ku Košiciam), **statická verejná IP** (drží sa aj po dealokácii).
VM zdieľal iné služby na portoch 8080/8081 — pre Janka Hraška stačí 22 a 80 (443 pre TLS).

```bash
az group create -n <RG> -l polandcentral
az vm create -g <RG> -n <VM> --image Ubuntu2204 --size Standard_D2s_v3 \
  --admin-username azureuser --ssh-key-values ~/.ssh/id_ed25519.pub \
  --public-ip-sku Standard --public-ip-address-allocation static --os-disk-size-gb 30
az vm open-port -g <RG> -n <VM> --port 80 --priority 900
```

## Inštalácia na VM

```bash
scp -r azure azureuser@<PUBLIC_IP>:~/janko-azure
ssh azureuser@<PUBLIC_IP> 'bash ~/janko-azure/setup_vm.sh'
```

[azure/setup_vm.sh](../azure/setup_vm.sh) nainštaluje nginx + autossh, nasadí
[nginx-janko.conf](../azure/nginx-janko.conf), [janko_tunnel.sh](../azure/janko_tunnel.sh),
[janko-tunnel.service](../azure/janko-tunnel.service) a vygeneruje **dedikovaný tunelový kľúč**
`~/.ssh/perun_tunnel_ed25519`. Zvyšné kroky ručne:

### 1. VPN do siete klastra (Pritunl)
Nainštalujte `pritunl-client` podľa <https://client.pritunl.com/#install>. Profil (URI
`pritunl://...`) a heslo vydáva VPN portál klastra — **do repa ani na disk VM v čitateľnej
podobe nepatria**.

```bash
pritunl-client add '<PROFIL_URI>'
pritunl-client list                          # ID profilu
pritunl-client start <ID> -p '<HESLO>'       # + zapnúť autostart profilu
```

VPN sprístupní len login uzly (SSH :22), nie compute uzly.

### 2. Obmedzený kľúč na login uzle
Na login uzol skopírujte [perun/agent_node.sh](../perun/agent_node.sh) do `$HOME` (`chmod 755`)
a do `~/.ssh/authorized_keys` pridajte verejný kľúč z VM **s obmedzením** podľa
[azure/authorized_keys.example](../azure/authorized_keys.example):

```
restrict,port-forwarding,command="/home/<USER>/agent_node.sh",permitopen="gpu01:8200",...,permitopen="gpu26:8200" ssh-ed25519 AAAA... janko-tunnel-azure
```

Kľúč vie iba (a) forward na `<uzol>:8200`, (b) spustiť `agent_node.sh`, ktorý vypíše aktuálny
master uzol. Žiadny shell, žiadny iný port či host. Osobný kľúč na VM nepatrí.

### 3. SSH config a štart tunela
`~/.ssh/config` podľa [azure/ssh_config.example](../azure/ssh_config.example) (Host `perun-login`), potom:

```bash
ssh perun-login true                         # vypíše master uzol (forced command)
sudo systemctl enable --now janko-tunnel
curl -s http://127.0.0.1:8200/health         # {"ok": true, ...}
```

`janko_tunnel.sh` zistí uzol cez `ssh perun-login true` a spustí
`autossh -M 0 -N -o ServerAliveInterval=15 -o ServerAliveCountMax=3 -L 127.0.0.1:8200:<uzol>:8200 perun-login`.
Keď job nebeží, skript skončí chybou a systemd to skúša každých 20 s.
**Po reštarte jobu (iný uzol):** `sudo systemctl restart janko-tunnel`.

### 4. nginx
`proxy_pass http://127.0.0.1:8200`, `proxy_buffering off` (SSE), `proxy_read_timeout 3600s`,
`client_max_body_size 20M`, `X-Real-IP` pre log otázok. Otvorte `http://<PUBLIC_IP>`.

## Šetrenie a znovuoživenie

```bash
az vm deallocate -g <RG> -n <VM>     # zastaví platbu za compute; IP + disk ostávajú
az vm start      -g <RG> -n <VM>
```

Pri dlhšej odstávke odporúčame z VM zmazať aj prístupy (Pritunl profil
`pritunl-client remove` + `~/.config/pritunl`, tunelový kľúč `shred`, blok `perun-login`
v `~/.ssh/config`, `systemctl disable janko-tunnel`) a obmedzený riadok z `authorized_keys`
na login uzle. Znovuoživenie = kroky 1–3 tejto kapitoly (nový kľúč, nový riadok v `authorized_keys`).

## Náklady (Azure, 2026)

| Stav | Cena |
|---|---|
| VM beží (D2s_v3, polandcentral) | ~47 €/mesiac |
| VM dealokovaný (statická IP + disk) | ~3–5 €/mesiac |

Pri predplatnom typu Azure Sponsorship sa zostatok kreditu nedá zistiť cez CLI/API —
len na <https://www.microsoftazuresponsorships.com/>.
