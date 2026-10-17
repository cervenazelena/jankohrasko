#!/bin/bash
# Stiahne MathJax (tex-svg-full, self-contained, ~2,3 MB) do agentic/static/mathjax.js.
# UI ho servíruje lokálne cez /static/mathjax.js (nie z CDN).
set -e
HERE="$(cd "$(dirname "$0")" && pwd)"
DEST="$HERE/../agentic/static"
VER="${MATHJAX_VERSION:-3.2.2}"
mkdir -p "$DEST"
curl -fsSL -o "$DEST/mathjax.js" "https://cdn.jsdelivr.net/npm/mathjax@${VER}/es5/tex-svg-full.js"
ls -la "$DEST/mathjax.js"
