#!/usr/bin/env bash
# Ovoz va semantik qatlam uchun model fayllari (repozitoriyada saqlanmaydi).
#   bash scripts/get-models.sh          # ovoz modeli (majburiy emas, lekin ovoz uchun kerak)
#   bash scripts/get-models.sh --all    # ustiga embedding modeli (~120 MB)
set -euo pipefail
cd "$(dirname "$0")/.."
DATA="${DATA_DIR:-data}/models"
mkdir -p "$DATA"

if [ ! -d "$DATA/vosk-model-small-uz-0.22" ]; then
  echo "Ovoz modeli yuklanmoqda (~50 MB)..."
  curl -L --fail -o "$DATA/vosk-uz.zip" \
    https://alphacephei.com/vosk/models/vosk-model-small-uz-0.22.zip
  unzip -q "$DATA/vosk-uz.zip" -d "$DATA" && rm -f "$DATA/vosk-uz.zip"
  echo "  tayyor: $DATA/vosk-model-small-uz-0.22"
else
  echo "Ovoz modeli allaqachon bor."
fi

if [ "${1:-}" = "--all" ]; then
  echo "Embedding modeli yuklanmoqda (~120 MB)..."
  ./venv/bin/python -m xalyava.ml --download 2>/dev/null \
    || python3 -m xalyava.ml --download
fi
echo "Tayyor."
