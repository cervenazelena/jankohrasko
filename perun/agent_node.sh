#!/bin/bash
# Na LOGIN uzle: vypíše master uzol bežiaceho jobu sglang_agentic (prvý uzol alokácie).
# Slúži ako forced command obmedzeného tunelového kľúča z frontend VM
# (viď azure/authorized_keys.example) — kľúč nevie spustiť nič iné.
# Skopíruj do $HOME na login uzle a nastav chmod 755. Názov jobu = JH_JOB_NAME v config.env.
JOB_NAME="sglang_agentic"
scontrol show hostnames "$(squeue -u "$USER" -n "$JOB_NAME" -t R -h -o %N | head -1)" | head -1
