# Žiadosť pre správcov klastra — PeerMappingOverride=1 pre DeepEP/IBGDA

Vzor žiadosti, ktorá na TUKE Perun prešla (júl 2026). Predchádzali jej menšie kroky:
MNNVL fabric (softvér — `patch_sglang_mnnvl.py`), `nvidia_peermem` a GDRCopy (správcovia).

## Zhrnutie
DeepSeek-V4-Pro cez SGLang na 2 uzloch, DeepEP nad NVSHMEM/IBGDA cez InfiniBand.
Chyba je izolovaná minimálnym testom (DeepEP `tests/legacy/test_internode.py`, BEZ SGLang) —
reprodukuje sa identicky, takže problém je v IBGDA vrstve, nie v SGLang ani v modeli:

```
WARN: cudaHostRegister with IoMemory failed with error=800   ← CUDA_ERROR_NOT_PERMITTED
[testing] Running with BF16 ... Global rank: 5, num_recv_tokens: -1   ← dispatch timeout
RuntimeError: DeepEP error: timeout (dispatch CPU)
```

`cudaHostRegister(..., cudaHostRegisterIoMemory)` mapuje MMIO (BAR) InfiniBand karty do
adresného priestoru GPU — IBGDA to potrebuje na zvonenie na doorbell NIC. Vracia
NOT_PERMITTED, lebo nvidia driver nemá nastavený `PeerMappingOverride=1`.

## Dôkaz (z compute uzla)
```
$ cat /proc/driver/nvidia/params | grep -E 'RegistryDwords|PeerMapping|StreamMemOPs'
EnableStreamMemOPs: 0
RegistryDwords: ""          ← PeerMappingOverride nie je nastavený
```

## Požiadavka (dokumentovaná štandardná požiadavka DeepEP/NVSHMEM IBGDA)
V `/etc/modprobe.d/nvidia.conf` na GPU uzloch:
```
options nvidia NVreg_EnableStreamMemOPs=1 NVreg_RegistryDwords="PeerMappingOverride=1;"
```
a znovu načítať modul `nvidia` (parameter sa číta len pri načítaní). Najčistejšie = reboot uzla.

Bez rebootu (po drainnutí GPU jobov):
```
sudo systemctl stop nvidia-persistenced
sudo systemctl stop dcgm-exporter nvidia-dcgm 2>/dev/null   # ak beží; over aj: sudo lsof /dev/nvidia*
sudo rmmod nvidia_peermem gdrdrv nvidia_uvm nvidia_modeset nvidia
sudo modprobe nvidia
sudo modprobe nvidia_uvm nvidia_peermem gdrdrv
sudo systemctl start nvidia-persistenced
```

**initramfs:** ak je modul `nvidia` v initramfs, zmena v `/etc/modprobe.d/` nestačí — treba
`sudo dracut -f` (RHEL/Rocky) alebo `sudo update-initramfs -u` (Debian/Ubuntu) a až potom reboot.

**Rollback:** odstrániť riadok z `/etc/modprobe.d/nvidia.conf`, `dracut -f`, reload/reboot.

Referencia: DeepEP `docs/nvshmem.md`.

## Overenie po zásahu
```
cat /proc/driver/nvidia/params | grep RegistryDwords    # obsahuje PeerMappingOverride=1
```
a `server/test_deepep_internode.sh` — warning `IoMemory` zmizne, dispatch prejde bez timeoutu.

## Poznámka
CPU-assisted IBGDA cez GDRCopy (`NVSHMEM_IBGDA_NIC_HANDLER=cpu`) PeerMappingOverride
nepotrebuje, ale v našich testoch dispatch aj tak zamŕzal — PeerMappingOverride je spoľahlivá cesta.
