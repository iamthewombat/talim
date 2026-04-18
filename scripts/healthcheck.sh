#!/usr/bin/env bash
# Verify all Talim services are healthy.
set -euo pipefail

fail() { echo "FAIL: $*" >&2; exit 1; }
pass() { echo "OK:   $*"; }

# 1) Redis
if docker exec talim-redis redis-cli ping >/dev/null 2>&1; then
    pass "redis ping"
else
    fail "redis not responding"
fi

# 2) Talim bridge (via nginx)
if curl -fsS http://localhost:8080/health >/dev/null 2>&1; then
    pass "bridge /health via nginx"
else
    fail "bridge /health unreachable through nginx"
fi

# 3) Talim direct (sanity)
if docker exec talim-app curl -fsS http://localhost:8000/talim/health >/dev/null 2>&1; then
    pass "bridge /talim/health direct"
else
    fail "bridge /talim/health direct failed"
fi

echo "All services healthy."
