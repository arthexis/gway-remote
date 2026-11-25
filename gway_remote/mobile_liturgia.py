"""Authenticated mobile bridge to the installed, revision-pinned Liturgia provider."""
import json
from .mcp_installed_providers import discover_installed_providers
from .mcp_node_providers import provider_call, NodeProviderError

TOOLS = frozenset(("readings", "translations", "books", "verse", "search", "analytics"))

def read(arguments):
    if type(arguments) is not dict or set(arguments) != {"tool", "arguments"}:
        raise ValueError("invalid_arguments")
    tool, params = arguments["tool"], arguments["arguments"]
    if type(tool) is not str or tool not in TOOLS or type(params) is not dict:
        raise ValueError("invalid_arguments")
    try:
        result = provider_call(discover_installed_providers(), provider="liturgia",
                               tool=tool, arguments=params, authorized_scope="read")
        content = result["content"]
        if len(content) != 1 or content[0]["type"] != "text":
            raise ValueError("invalid_provider_result")
        raw = content[0]["text"]
        if type(raw) is not str or len(raw.encode("utf-8")) > 128 * 1024:
            raise ValueError("invalid_provider_result")
        data = json.loads(raw)
        if result.get("isError"):
            if data.get("code") == "invalid_arguments":
                raise ValueError("invalid_arguments")
            raise RuntimeError("liturgia_unavailable")
        if type(data) is not dict or data.get("schema_version") != 1:
            raise ValueError("invalid_provider_result")
        return data
    except (NodeProviderError, OSError, KeyError, TypeError, IndexError):
        raise RuntimeError("liturgia_unavailable") from None
    except ValueError:
        raise ValueError("invalid_arguments") from None
