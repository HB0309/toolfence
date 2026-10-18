#!/usr/bin/env bash
set -euo pipefail

GALAXIUM_URL="https://github.com/IBM/galaxium-travels.git"
GALAXIUM_HASH="6163380cdb4ba50caee0b82c66afc4700d90546a"
GALAXIUM_DIR="targets/galaxium"

NANOBOT_URL="https://github.com/HKUDS/nanobot.git"
NANOBOT_HASH="948ce3824653d55b18ff1c618613fb642679bab7"
NANOBOT_DIR="targets/nanobot"

if [ ! -d "$GALAXIUM_DIR" ]; then
    git clone "$GALAXIUM_URL" "$GALAXIUM_DIR"
    git -C "$GALAXIUM_DIR" checkout "$GALAXIUM_HASH"
fi

if [ ! -d "$NANOBOT_DIR" ]; then
    git clone "$NANOBOT_URL" "$NANOBOT_DIR"
    git -C "$NANOBOT_DIR" checkout "$NANOBOT_HASH"
fi

for patch in $(ls targets/galaxium-patches/*.patch 2>/dev/null | sort); do
    name=$(basename "$patch")
    if git -C "$GALAXIUM_DIR" apply --check "$patch" 2>/dev/null; then
        git -C "$GALAXIUM_DIR" apply "$patch"
    else
        echo "[SKIP] $name"
    fi
done

pip install -e ".[dev]" -e targets/nanobot -r targets/galaxium/booking_system_backend/requirements.txt

(cd targets/galaxium/booking_system_inventory_hold_service && mvn -q clean package -DskipTests)
