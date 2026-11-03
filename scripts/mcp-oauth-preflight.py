#!/usr/bin/env python3
"""Non-activating M2.1 OAuth discovery preflight for self-hosted GWA MCP.

Uses only unauthenticated public metadata. No passwords, tokens or client secrets.
Does NOT prove token issuance or activate a public gateway.
"""
import json
import sys
from urllib.parse import urlsplit
from urllib.request import Request, urlopen

MCP_RESOURCE = "https://remote.arthexis.com/mcp"
RESOURCE_METADATA = "https://remote.arthexis.com/.well-known/oauth-protected-resource"
MAX_BYTES = 65536


def require_https(value):
    if not isinstance(value, str):
        raise ValueError("invalid_url")
    p = urlsplit(value)
    if p.scheme != "https" or not p.hostname or p.username or p.password or p.fragment:
        raise ValueError("invalid_url")
    return value


def load_json(url):
    require_https(url)
    req = Request(url, headers={"Accept": "application/json"})
    with urlopen(req, timeout=8) as response:
        raw = response.read(MAX_BYTES + 1)
        if len(raw) > MAX_BYTES:
            raise ValueError("metadata_too_large")
        return json.loads(raw)


def validate_resource(metadata, expected_resource=MCP_RESOURCE):
    if not isinstance(metadata, dict) or metadata.get("resource") != expected_resource:
        raise ValueError("resource_mismatch")
    servers = metadata.get("authorization_servers")
    if not isinstance(servers, list) or len(servers) != 1:
        raise ValueError("expected_single_issuer")
    return require_https(servers[0])


def validate_authorization(metadata, issuer):
    if not isinstance(metadata, dict) or metadata.get("issuer") != issuer:
        raise ValueError("issuer_mismatch")
    for key in ("authorization_endpoint", "token_endpoint", "jwks_uri"):
        require_https(metadata.get(key))
    if "S256" not in metadata.get("code_challenge_methods_supported", []):
        raise ValueError("pkce_s256_required")
    grants = metadata.get("grant_types_supported", ["authorization_code"])
    if "authorization_code" not in grants:
        raise ValueError("authorization_code_required")
    methods = metadata.get("token_endpoint_auth_methods_supported", [])
    if not any(m in methods for m in ("none", "client_secret_basic", "client_secret_post", "private_key_jwt")):
        raise ValueError("unsupported_client_auth")
    return True


def verify(resource_loader=load_json, issuer_loader=load_json):
    resource = resource_loader(RESOURCE_METADATA)
    issuer = validate_resource(resource)
    # Discovery URL must be configured explicitly for providers with path-based
    # issuers; do not guess the issuer metadata URL or rewrite issuer paths.
    metadata_url = resource.get("gway_authorization_server_metadata_url")
    if metadata_url is not None:
        raise ValueError("nonstandard_metadata_field")
    return issuer


def main():
    # Fetch the public resource metadata and inspect its declared issuer only.
    # A provider-specific issuer metadata path must be obtained from its
    # documented .well-known endpoint and passed as argv[1].
    if len(sys.argv) != 2:
        print("Usage: python3 scripts/mcp-oauth-preflight.py HTTPS_PROVIDER_METADATA_URL", file=sys.stderr)
        return 2
    try:
        provider_url = require_https(sys.argv[1])
        issuer = verify()
        validate_authorization(load_json(provider_url), issuer)
    except Exception:
        # Do not print raw URLs or provider responses; they may contain secrets.
        print("BLOCKED: MCP OAuth discovery/PKCE preflight", file=sys.stderr)
        return 1
    print("PASS: MCP resource, exact issuer, HTTPS endpoints, PKCE S256 and client auth metadata")
    print("NOT TESTED: login, token audience/scope, policy, gateway routing or ChatGPT connection")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
