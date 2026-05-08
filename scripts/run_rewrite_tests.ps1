$ErrorActionPreference = "Stop"

$python = "C:\Users\kyane\AppData\Local\Programs\Python\Python310\python.exe"
$root = Split-Path -Parent $PSScriptRoot

Push-Location $root
try {
  & $python -m compileall -q .
  & $python -m unittest discover -s tests -v
  npm --prefix whisperer-app run typecheck
  npm --prefix whisperer-app run build
}
finally {
  Pop-Location
}
