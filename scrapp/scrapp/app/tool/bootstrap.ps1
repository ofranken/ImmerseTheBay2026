# Windows version of tool/bootstrap.sh
$ErrorActionPreference = "Stop"
Set-Location (Join-Path $PSScriptRoot "..")
flutter create --org com.scrapp --project-name scrapp --platforms=android,ios .
Remove-Item -Recurse -Force -ErrorAction SilentlyContinue android/app/src/main/kotlin/com/scrapp/scrapp
New-Item -ItemType Directory -Force android/app/src/main/assets | Out-Null
$model = "android/app/src/main/assets/efficientdet_lite0.tflite"
if (-not (Test-Path $model)) {
  Invoke-WebRequest -Uri "https://storage.googleapis.com/mediapipe-models/object_detector/efficientdet_lite0/int8/latest/efficientdet_lite0.tflite" -OutFile $model
}
flutter pub get
Write-Host "Done. Next: flutter run --dart-define=API_BASE=http://<your-computer-LAN-IP>:8000"
