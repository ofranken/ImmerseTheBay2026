#!/usr/bin/env bash
# One-time setup: generate the Flutter platform scaffolding around Scrapp's own files,
# fetch the on-device object detector, and install packages.
set -euo pipefail
cd "$(dirname "$0")/.."

# Creates only missing files (Scrapp's android/ overrides are kept).
flutter create --org com.scrapp --project-name scrapp --platforms=android,ios .
# flutter create adds a default MainActivity under com/scrapp/scrapp; Scrapp's lives in com/scrapp/app.
rm -rf android/app/src/main/kotlin/com/scrapp/scrapp

mkdir -p android/app/src/main/assets
MODEL=android/app/src/main/assets/efficientdet_lite0.tflite
[ -f "$MODEL" ] || curl -fL -o "$MODEL" \
  https://storage.googleapis.com/mediapipe-models/object_detector/efficientdet_lite0/int8/latest/efficientdet_lite0.tflite

flutter pub get
echo "Done. Next: flutter run --dart-define=API_BASE=http://<your-computer-LAN-IP>:8000"
