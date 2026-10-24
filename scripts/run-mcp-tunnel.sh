#!/bin/sh
# Private GWay-001 MCP tunnel runtime. systemd loads the two private env files.
set -eu
: "${CONTROL_PLANE_API_KEY:?tunnel runtime key not configured}"
: "${CONTROL_PLANE_TUNNEL_ID:?tunnel ID not configured}"
: "${GWAY_MCP_BEARER_TOKEN:?local MCP Bearer token not configured}"
case "$CONTROL_PLANE_TUNNEL_ID" in
  tunnel_*) ;;
  *) echo "Invalid tunnel ID" >&2; exit 1 ;;
esac
# The official tunnel client resolves static per-origin headers. Never send the
# local token to the OpenAI control plane; it is scoped to MCP loopback requests.
export MCP_SERVER_URL="http://127.0.0.1:8770/mcp"
export MCP_EXTRA_HEADERS="Authorization: Bearer ${GWAY_MCP_BEARER_TOKEN}"
export MCP_DISCOVERY_EXTRA_HEADERS="Authorization: Bearer ${GWAY_MCP_BEARER_TOKEN}"
exec tunnel-client run --health.listen-addr 127.0.0.1:8771
