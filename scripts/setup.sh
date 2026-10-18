#!/usr/bin/env bash
# Linux/Codespaces twin of scripts/setup.ps1: pinned targets, patches, two Python envs, Java build.
set -euo pipefail
cd "$(dirname "$0")/.."

clone_at() {
  local url=$1 hash=$2 dir=$3
  if [ ! -d "$dir/.git" ]; then git clone --quiet "$url" "$dir"; fi
  git -C "$dir" checkout --quiet "$hash"
}
clone_at https://github.com/IBM/galaxium-travels.git 6163380cdb4ba50caee0b82c66afc4700d90546a targets/galaxium
clone_at https://github.com/HKUDS/nanobot.git 948ce3824653d55b18ff1c618613fb642679bab7 targets/nanobot

for patch in $(ls targets/galaxium-patches/*.patch | sort); do
  if git -C targets/galaxium apply --check "$PWD/$patch" 2>/dev/null; then
    git -C targets/galaxium apply "$PWD/$patch"; echo "[APPLY] $(basename "$patch")"
  else
    echo "[SKIP] $(basename "$patch")"
  fi
done

# Galaxium backend env (mcp 1.30, same as the local backend .venv)
python -m venv .venv-galaxium
.venv-galaxium/bin/pip install -q -r targets/galaxium/booking_system_backend/requirements.txt

# Agent + dashboard env: nanobot (mcp<2) plus toolfence without its mcp>=2.3 pin (only toolfence/bob needs it)
python -m venv .venv-live
.venv-live/bin/pip install -q -e targets/nanobot
.venv-live/bin/pip install -q --no-deps -e .
.venv-live/bin/pip install -q "pydantic>=2" "jsonschema>=4"

(cd targets/galaxium/booking_system_inventory_hold_service && mvn -q clean package -DskipTests)
echo "Setup complete"
