#!/bin/bash
#SBATCH --partition=gpu_long
#SBATCH --nodes=1
#SBATCH --ntasks=1
#SBATCH --cpus-per-task=4
#SBATCH --gres=gpu:1
#SBATCH --time=0-00:10:00
#SBATCH --job-name=diag_gdrcopy
#SBATCH --output=diag_gdrcopy_%j.out
#
#     sbatch -A <ACCOUNT> --qos <QOS> server/diag_gdrcopy.sh
#
# Overí na GPU uzle predpoklady IBGDA: gdrdrv modul, /dev/gdrdrv, libgdrapi, gdrcopy_sanity.
# Doplnkovo: cat /proc/driver/nvidia/params | grep -E 'RegistryDwords|StreamMemOPs'
#   musí ukázať PeerMappingOverride=1 a EnableStreamMemOPs: 1.

echo "=== diag_gdrcopy: $(date) na $(hostname) ==="

echo "--- gdrdrv modul ---"
lsmod | grep gdrdrv

echo "--- /proc/devices (gdrdrv major cislo) ---"
grep -i gdrdrv /proc/devices || echo "gdrdrv NIE JE v /proc/devices (modul nezaregistroval char device!)"

echo "--- /dev/gdrdrv ---"
ls -la /dev/gdrdrv 2>&1

echo "--- /dev obsahuje 'gdr'? ---"
ls -la /dev/ | grep -i gdr || echo "(ziadny gdr* v /dev)"

echo "--- libgdrapi hladanie na celom filesystéme (bezne cesty) ---"
for p in /usr/local/lib /usr/local/lib64 /usr/lib /usr/lib64 /usr/lib/x86_64-linux-gnu /opt/gdrcopy/lib /opt/gdrcopy/lib64; do
    ls -la "$p"/libgdrapi* 2>/dev/null && echo "  (najdene v $p)"
done

echo "--- gdrcopy CLI nastroje (ak su nainstalovane) ---"
which gdrcopy_copybw gdrcopy_sanity gdrcopy_pplat 2>/dev/null || echo "(gdrcopy CLI nastroje nie su v PATH)"

echo "--- skus gdrcopy_sanity ak existuje ---"
if command -v gdrcopy_sanity >/dev/null 2>&1; then
    gdrcopy_sanity 2>&1 | tail -20
else
    echo "(gdrcopy_sanity nenajdeny, preskakujem funkcny test)"
fi

echo "--- udev pravidlo pre gdrdrv (ak existuje) ---"
find /usr/lib/udev/rules.d /etc/udev/rules.d -iname '*gdr*' 2>/dev/null || echo "(ziadne udev pravidlo pre gdrdrv najdene)"

echo "--- skus manualne vytvorit device node (test permissions) ---"
MAJOR=$(grep -i gdrdrv /proc/devices | awk '{print $1}')
if [ -n "$MAJOR" ]; then
    echo "Major cislo gdrdrv: $MAJOR"
    sudo -n mknod /dev/gdrdrv c "$MAJOR" 0 2>&1 && echo "device node vytvoreny (sudo bez hesla fungovalo)" || echo "sudo mknod zlyhal (ocakavane, netreba root prava)"
else
    echo "Major cislo sa nenaslo - modul asi nezaregistroval char device"
fi

echo "=== KONIEC diag_gdrcopy: $(date) ==="
