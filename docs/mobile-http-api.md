# Mobile HTTP adapter (Phase 1, chunk 2)

This is a **local development interface**, not a production HTTPS deployment. It does not install a service, open a non-loopback socket, create a database, or add a runtime dependency.

## Run

Set a strong random token in the current shell, then run:

```sh
export GWAY_REMOTE_API_TOKEN="$(python3 -c 'import secrets; print(secrets.token_urlsafe(32))')"
python3 -m gway_remote api --host 127.0.0.1 --port 8765
```

In another shell with the same token:

```sh
curl -H "Authorization: Bearer $GWAY_REMOTE_API_TOKEN" http://127.0.0.1:8765/api/v1/commands
curl -H "Authorization: Bearer $GWAY_REMOTE_API_TOKEN" -H 'Content-Type: application/json' \
  -d '{"command":"probe-csms","arguments":{}}' http://127.0.0.1:8765/api/v1/execute
```

Endpoints: `GET /api/v1/health`, `GET /api/v1/commands`, `POST /api/v1/execute`. All require the bearer token. Only `probe-csms` and `status` are allowed, with no arguments. Responses are JSON; unknown operations and unexpected parameters are rejected. Request bodies are capped at 8 KiB and response bodies at 1 MiB.

The adapter uses standard-library `ThreadingHTTPServer` and binds only to a loopback IP address. It serves **plaintext HTTP on loopback**: do not port-forward or expose it to other devices. TLS termination, rate limiting, request time budgets, credentials, and production hosting require a separate security/deployment review before phone access.

Run tests with `python3 -m unittest discover -s tests -v`.
