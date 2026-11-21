# Bootstrap genérico #641 — incremento A (runtime del ejecutor)

Este incremento no activa todavía la URL HTTPS integral ni instala nuevos
servicios. Converge usando el Ansible existente la identidad seleccionada sin
asumir que su username sea `arthe`.

- El verificador de relay de SSH/visudo acepta cualquier cuenta Unix con
  formato validado (rth, arthe, etc.), exige comando e identidad exactos y
  rechaza root y gway-relay.
- El entorno de un operador distinto del legacy gway-exec sólo añade la ruta
  fija del socket Bastion si es un socket privado y propiedad de su UID;
  nunca hereda SSH_AUTH_SOCK desde la petición.
- Antes de un cambio de identidad, Ansible asegura linger y arranca
  user@UID.service sin reiniciar managers activos. Sólo sobre directorios
  reales propiedad del usuario, admite runtime mode 0700 o el legado 0770,
  corrige exclusivamente el modo 0770→0700 sin chown y exige un bus socket
  real con UID correcto. Otros modos, symlinks y otros owners fallan cerrado.
- La excepción file-reader sigue siendo únicamente de gway-001, pero usa el
  ejecutor configurado, no una cuenta hardcodeada.

No cambia grants, Watchtower, WireGuard, SSH keys, ledger, OAuth, inventario,
ni producción 002/005. Tests son herméticos; no validan field readiness.

## Pendiente dentro de #641

Integrar instalador del paquete, relay y verificación terminal desde la URL,
con SHA revisado y recibos por etapas; automatizar en Watchtower pin por clave
atestada y grant/revoke único deny-by-default. Validar fresh/repair/rollback
y nodo canario antes de activar producción.
