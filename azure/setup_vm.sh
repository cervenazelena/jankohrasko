#!/bin/bash
# Inštalácia frontendu na čerstvý Ubuntu 22.04 VM (spúšťa azureuser zo skopírovaného azure/):
#     scp -r azure azureuser@<PUBLIC_IP>:~/janko-azure && ssh azureuser@<PUBLIC_IP> 'bash ~/janko-azure/setup_vm.sh'
# VPN klienta (pritunl-client) a tunelový kľúč treba doplniť ručne — viď docs/04_frontend_azure.md.
set -euo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"

sudo apt-get update
sudo apt-get install -y nginx autossh curl

# nginx reverse-proxy
sudo cp "$HERE/nginx-janko.conf" /etc/nginx/sites-available/janko
sudo ln -sf /etc/nginx/sites-available/janko /etc/nginx/sites-enabled/janko
sudo rm -f /etc/nginx/sites-enabled/default
sudo nginx -t && sudo systemctl reload nginx

# tunel
install -m 755 "$HERE/janko_tunnel.sh" "$HOME/janko_tunnel.sh"
sudo cp "$HERE/janko-tunnel.service" /etc/systemd/system/janko-tunnel.service
sudo systemctl daemon-reload

# dedikovaný tunelový kľúč (len ak ešte nie je)
mkdir -p "$HOME/.ssh" && chmod 700 "$HOME/.ssh"
if [ ! -f "$HOME/.ssh/perun_tunnel_ed25519" ]; then
    ssh-keygen -t ed25519 -f "$HOME/.ssh/perun_tunnel_ed25519" -N '' -C janko-tunnel-azure
fi
echo
echo "Verejný kľúč pre authorized_keys na login uzle (s obmedzením z authorized_keys.example):"
cat "$HOME/.ssh/perun_tunnel_ed25519.pub"
echo
echo "Ďalej: ~/.ssh/config podľa ssh_config.example, VPN (pritunl-client), potom:"
echo "    sudo systemctl enable --now janko-tunnel"
