#!/usr/bin/env bash
# Start Java hold service (8082), Galaxium backend (8001), then the live dashboard (8080).
set -uo pipefail
cd "$(dirname "$0")/.."
ROOT=$PWD
HOLD=targets/galaxium/booking_system_inventory_hold_service
BACK=targets/galaxium/booking_system_backend

(cd "$HOLD" && setsid nohup java -jar target/inventory-hold-service-1.0.0.jar --server.port=8082 > /tmp/java.log 2>&1 &)
(cd "$BACK" && JAVA_SERVICE_URL=http://localhost:8082 setsid nohup "$ROOT/.venv-galaxium/bin/python" server.py > /tmp/galaxium.log 2>&1 &)

for _ in $(seq 1 90); do
  curl -fs http://localhost:8001/ > /dev/null && curl -fs http://localhost:8082/api/v1/health > /dev/null && break
  sleep 2
done

(PYTHONUNBUFFERED=1 setsid nohup "$ROOT/.venv-live/bin/toolfence" serve --host 0.0.0.0 --port 8080 --live > /tmp/dashboard.log 2>&1 &)

for _ in $(seq 1 30); do
  curl -fs http://localhost:8080/api/live/status > /dev/null && break
  sleep 1
done
if curl -fs http://localhost:8080/api/live/status > /dev/null; then
  echo "ToolFence dashboard is up on port 8080"
else
  echo "Dashboard did not start; see /tmp/dashboard.log"
fi
