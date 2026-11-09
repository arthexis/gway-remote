"""Opt-in SSH ForceCommand entrypoint for a dedicated read-only relay identity.

Not installed or enabled by importing this module. The SSH operator must bind
this entrypoint to a separate, root-managed public key and account.
"""
from .node_exec_protocol import main


if __name__ == "__main__":
    raise SystemExit(main(read_only=True))
