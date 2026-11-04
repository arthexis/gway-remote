# GWay MCP executor command exports

The MCP shell runs as the locked `gway-exec` account via `/bin/sh -c`, with
`HOME=/var/lib/gway-exec`. It must **not** load `arthe`'s shell startup
files, enter `/home/arthe`, switch user, or read operator credentials.

`/usr/local/libexec/gway-remote-tools` is a root-owned executable export
directory. It is prepended to the executor shell PATH. Ansible provisions
the initial **read-only `guide`** command there. The exported guide is a
separate executor-visible index, not a copy of the interactive `arthe` index:
it reports only the commands installed in the shared export directory. It
supports `guide`, `guide --all`, `guide search TEXT`,
`guide show COMMAND` and `guide where COMMAND`. The normal operator
inventory remains unchanged.

An additional command must undergo explicit review of all its source,
interpreter, supporting files, privilege needs and data access before
being installed as a root-owned export. Never place a symlink to
user-writable or private code here. This directory controls discovery
and packaging, **not authorization**: generic shell commands remain
governed by the existing OS account, OAuth scope, eligibility and job limits.

## ChatGPT / MCP operating guidance

Prefer dedicated MCP tools when available. For another requested host-local
command, check the exact node's capabilities and use
`node_exec_preview`, `node_exec`, then `node_result` with an authorized
fresh request ID. Do not assume an arbitrary command is a
`gway-remote` CLI subcommand. If the shell says command not found, inspect
`id`, `HOME`, `PATH`, the shared export and missing dependencies.
Do not automatically elevate privileges, switch to `arthe`, or modify
the home directory. Command discovery is not permission to execute a
dangerous action.

## After Ansible deployment

Through real MCP execute scope on `gway-001`, verify:
```sh
id
command -v guide
guide
guide where guide
test ! -r /home/arthe/.bashrc
```
Keep the real result evidence on issue #364. CI alone cannot verify
the node's actual deployment or local permission boundaries.
