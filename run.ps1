# run.ps1 — Run the KuKu Promo Finder on Windows
# Sets UTF-8 encoding so Unicode symbols in the output print correctly.
#
# Usage: .\run.ps1

$env:PYTHONIOENCODING = 'utf-8'
python main.py
