#!/usr/bin/env bash
# Manage the AgentDojo MCP bridge (REST :9000 for init/finish, MCP :9001 for tools).
#
#   ./bridge.sh start | stop | status | log
#
# Ports: API_PORT (9000) / MCP_PORT (9001). Log: bridge.log, pid: .bridge.pid.
set -euo pipefail
cd "$(dirname "$0")"
API_PORT="${API_PORT:-9000}"
MCP_PORT="${MCP_PORT:-9001}"
PIDFILE=.bridge.pid
LOG=bridge.log

alive() { [ -f "$PIDFILE" ] && kill -0 "$(cat "$PIDFILE")" 2>/dev/null; }
rest_up() { curl -s -o /dev/null "http://127.0.0.1:$API_PORT/docs"; }

case "${1:-}" in
  start)
    if alive && rest_up; then echo "bridge already running (pid $(cat "$PIDFILE"))"; exit 0; fi
    [ -x .venv/bin/python ] || { echo "no .venv; run ./setup.sh first" >&2; exit 1; }
    mkdir -p mcp_results
    # setsid puts the server and its workers in their own process group so stop can kill them all.
    if command -v setsid >/dev/null 2>&1; then
      setsid nohup .venv/bin/python agentdojo-mcp/mcp_server.py \
        --api-port "$API_PORT" --mcp-port "$MCP_PORT" --results-dir mcp_results >"$LOG" 2>&1 &
    else
      nohup .venv/bin/python agentdojo-mcp/mcp_server.py \
        --api-port "$API_PORT" --mcp-port "$MCP_PORT" --results-dir mcp_results >"$LOG" 2>&1 &
    fi
    echo $! >"$PIDFILE"
    for _ in $(seq 1 60); do
      if rest_up; then echo "bridge up: REST :$API_PORT, MCP :$MCP_PORT (pid $(cat "$PIDFILE"), log $LOG)"; exit 0; fi
      alive || { echo "bridge died; see $LOG" >&2; tail -20 "$LOG" >&2; exit 1; }
      sleep 1
    done
    echo "bridge did not answer on :$API_PORT within 60s; see $LOG" >&2; exit 1 ;;
  stop)
    if [ -f "$PIDFILE" ]; then
      pid=$(cat "$PIDFILE")
      kill -- "-$pid" 2>/dev/null || kill "$pid" 2>/dev/null || true
      pkill -P "$pid" 2>/dev/null || true
      rm -f "$PIDFILE"
    fi
    pkill -f "agentdojo-mcp/mcp_server.py" 2>/dev/null || true
    echo "bridge stopped" ;;
  status)
    if alive && rest_up; then echo "running (pid $(cat "$PIDFILE"))"; else echo "not running"; exit 1; fi ;;
  log) tail -f "$LOG" ;;
  *) echo "usage: $0 start|stop|status|log" >&2; exit 2 ;;
esac
