#!/usr/bin/env python3
"""
Patch SGLang deepep.py: env-gate allow_mnnvl (skutočný root cause MNNVL fabric crashu).

ZISTENIE (deep_ep 2.1.0 na TUKE):
  - deep_ep legacy.py posiela `allow_mnnvl` ako 8. pozičný arg do C++ _C.Buffer(...),
    čo je presne C++ parameter `use_fabric`.
  - SGLang deepep.py natvrdo nastavuje allow_mnnvl=True → C++ use_fabric=True →
    shared_memory.hpp:69 cuMemCreate(CU_MEM_HANDLE_TYPE_FABRIC) → NOT_PERMITTED(800).
  - Admin potvrdil: TUKE má medzi uzlami len InfiniBand, žiadny cross-node NVLink fabric.
  - allow_mnnvl=False navyše nastaví NVSHMEM_DISABLE_MNNVL=1 → NVSHMEM použije IB RDMA.

Preto C++ rebuild NETREBA — stačí táto Python zmena.

Použitie:
    python patch_sglang_mnnvl.py            # diagnostika (dry-run)
    python patch_sglang_mnnvl.py --apply    # aplikuj

Runtime prepínač: SGLANG_DISABLE_MNNVL_FABRIC=1  → allow_mnnvl=False (fabric OFF)
"""

import sys
import shutil
import argparse
from pathlib import Path

def _default_deepep_py() -> Path:
    """deepep.py v aktuálnom python env (spúšťaj pythonom z SGLang env)."""
    import sysconfig
    return (Path(sysconfig.get_paths()["purelib"])
            / "sglang/srt/layers/moe/token_dispatcher/deepep.py")


DEEPEP_PY = _default_deepep_py()

OLD = """            # TODO can be false when unneeded
            allow_mnnvl=True,
        )"""

NEW = """            # TODO can be false when unneeded
            # PATCH(TUKE): allow_mnnvl → deep_ep 2.1.0 mapuje na C++ use_fabric (8. Buffer arg).
            # IB-only klaster (žiadny cross-node NVLink fabric) → FABRIC handle = NOT_PERMITTED(800).
            # allow_mnnvl=False navyše nastaví NVSHMEM_DISABLE_MNNVL=1 → NVSHMEM cez IB RDMA.
            allow_mnnvl=(__import__("os").environ.get("SGLANG_DISABLE_MNNVL_FABRIC", "0") != "1"),
        )"""

MARKER = 'PATCH(TUKE): allow_mnnvl'


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--file", type=Path, default=DEEPEP_PY, help="cesta k SGLang deepep.py")
    ap.add_argument("--apply", action="store_true", help="skutočne aplikuj (bez toho len dry-run)")
    args = ap.parse_args()

    f = args.file
    if not f.exists():
        print(f"CHYBA: {f} neexistuje")
        sys.exit(1)

    src = f.read_text()

    if MARKER in src:
        print("UŽ PATCHNUTÉ — allow_mnnvl je env-gated (SGLANG_DISABLE_MNNVL_FABRIC=1 ho vypne).")
        return

    if OLD not in src:
        print("CHYBA: očakávaný blok 'allow_mnnvl=True,' nenájdený.")
        print("Súbor sa možno zmenil. Relevantné riadky:")
        for i, line in enumerate(src.splitlines(), 1):
            if "allow_mnnvl" in line:
                print(f"  {i}: {line}")
        sys.exit(1)

    new_src = src.replace(OLD, NEW)

    if args.apply:
        bak = f.with_suffix(".py.bak")
        shutil.copy2(f, bak)
        f.write_text(new_src)
        print(f"PATCH OK — allow_mnnvl teraz env-gated. Záloha: {bak}")
        print("Overenie riadku:")
        for i, line in enumerate(new_src.splitlines(), 1):
            if "allow_mnnvl=(" in line:
                print(f"  {i}: {line.strip()}")
        print("\nĎalší krok: sbatch perun/serve_agentic.sh")
    else:
        print("DRY-RUN — blok nájdený, patch pripravený. Spusti s --apply.")
        print("Náhľad zmeny (nový riadok):")
        print('  allow_mnnvl=(__import__("os").environ.get("SGLANG_DISABLE_MNNVL_FABRIC", "0") != "1"),')


if __name__ == "__main__":
    main()
