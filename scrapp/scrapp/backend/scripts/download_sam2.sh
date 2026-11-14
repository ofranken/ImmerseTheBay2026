#!/usr/bin/env bash
# Downloads the SAM 2.1 Hiera-Large checkpoint (Apache-2.0) into backend/checkpoints/.
set -euo pipefail
cd "$(dirname "$0")/.."
mkdir -p checkpoints
URL="https://dl.fbaipublicfiles.com/segment_anything_2/092824/sam2.1_hiera_large.pt"
[ -f checkpoints/sam2.1_hiera_large.pt ] || wget -q --show-progress -O checkpoints/sam2.1_hiera_large.pt "$URL"
echo "SAM 2.1 checkpoint ready: checkpoints/sam2.1_hiera_large.pt"
