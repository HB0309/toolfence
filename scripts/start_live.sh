#!/usr/bin/env bash
set -euo pipefail

nohup java -Dserver.port=8082 -jar targets/galaxium/booking_system_inventory_hold_service/target/inventory-hold-service-1.0.0.jar > /tmp/java.log 2>&1 &
(cd targets/galaxium/booking_system_backend && JAVA_SERVICE_URL=http://localhost:8082 nohup python server.py > /tmp/galaxium.log 2>&1 &)
nohup toolfence serve --host 0.0.0.0 --port 8080 --live
