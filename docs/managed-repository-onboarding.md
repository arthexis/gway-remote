# Dar de alta un repositorio en GWay Remote: auditoría con OCPP Reports

Caso de referencia: [issue #563](https://github.com/arthexis/gway-remote/issues/563).
Este procedimiento describe el **catálogo Appliance Deploy para gway-001**, no el
despliegue federado de proveedores MCP ni el Collector de ocpp-abb-1.

## Dos contratos diferentes

- Appliance Deploy: CLI `gway-remote deploy` → workflow manual propietario
  `.github/workflows/appliance-deploy.yml` → admisión con inventario Ansible
  → runner de `gway-001` → `deploy-batch` → instalador `deploy.sh` del propio
  repositorio, con SHA exacto, CI validado, lock y recibo.
- MCP `node_deploy_*`: exige un proveedor **instalado**, una declaración de
  despliegue del propio nodo en `/etc/gway-mcp-providers/`, transporte y
  autorización de Watchtower. No nace automáticamente al permitir un repo
  en el inventario de Appliance Deploy. Durante #563, los previews MCP
  retornaron `deployment_preview_unavailable`, también para otro proveedor.

La lista `remote_managed_repositories` admite únicamente el host declarado.
No amplía roles, identidades SSH, acceso a nodos de cliente ni capacidad de
ejecución genérica.

## Checklist para un repositorio verdaderamente nuevo

1. Auditar su instalador canónico, modo no-root, rol persistido, release activo,
   rutas, servicios, estado previo, salud, lock, idempotencia, límites de recursos
   y rollback. Rechazar entradas que dependan de un rol por defecto ambiguo.
2. Agregar el par (nombre, repositorio) a `gway_remote/reconcile.py::TARGETS`.
3. Implementar adaptador de SHA exacto al `deploy.sh` propietario en
   `gway_remote/__main__.py` y declararlo en `best_effort.INSTALLERS`. No
   duplicar Ansible ni construir un instalador paralelo.
4. Agregar evidencia de release/sonda read-only, o preservar `unknown` hasta
   disponer de una sonda verificable; Git HEAD y resultado del dispatch no son
   evidencia de instalación ni de salud.
5. Autorizar explícitamente el nodo en
   `ansible/inventory/deployment.yml::remote_managed_repositories`; dejar
   los demás nodos con denegación por defecto.
6. Agregar opción `workflow_dispatch`, job independiente con guardas
   `github.actor`, host, admisión y CI, dependencias y entrada en el resumen
   de `.github/workflows/appliance-deploy.yml`. El selector de CLI se deriva
   del catálogo `TARGETS`, sin excepciones codificadas para Reports.
7. Probar casos positivos/negativos, selector, `--all` y subconjunto autorizado,
   errores de CI/instalación, locks, nodos prohibidos y roles incompatibles.
   `tests/deployment/test_repository_onboarding.py` detecta registros
   incompletos entre catálogo, instaladores, CLI y workflow.
8. Revisar PR Draft, CI y estado real del nodo (incluidos timers, otros jobs,
   SHA instalado y rol), antes de autorizar Ready, merge o despliegue.
   La integración de Remote en `main` puede actualizar automáticamente su
   propio backend e inventario: no se debe confundir este efecto con instalar
   deliberadamente la aplicación añadida.

## Medición de fricción y mejoras futuras

Un nuevo repositorio requiere, como mínimo, **siete áreas**: catálogo,
adaptador/instalador, sonda, inventario, opciones/jobs/resumen de workflow,
pruebas y documentación/aceptación. La duplicación más clara es el job estático
de Actions y las tres representaciones de cada target (catálogo, inventario,
workflow). Un manifiesto versionado único y una validación/generación segura de
jobs podrían reducirla, pero necesitan una PR separada que preserve los controles
de actor, host, locks, jobs independientes y los efectos de `--all`.

Para **reincorporar** Reports, catálogo, instalador y sonda **ya existían**.
Faltaban: autorización de gway-001 en el inventario, selector de CLI, opción,
job y resumen del workflow. Los tests existentes de inventarios parciales
siguen denegando Reports cuando **ese inventario de prueba** no lo autoriza.
Añadimos además una verificación del rol persistido de Reports para evitar que
`deploy.sh` interprete un host nuevo como instalación `terminal` sin revisión.

## Aceptación de campo separada

El destino del cambio es **gway-001**, nunca `ocpp-abb-1`.
[ocpp-reports#211](https://github.com/arthexis/ocpp-reports/issues/211)
autoriza un trabajo diferente para el Collector y Dashboard de ese nodo.

Antes de cualquier despliegue efectivo: recuperar en solo lectura el rol
`/opt/ocpp-reports/role`, release `current`, SHA, servicios, timers y salud,
capacidad de rollback, locks, concurrencia con gway-remote#561, CI del SHA
aprobado y estado de la vigilancia local. Si faltan o son ambiguos, detenerse;
no inventar rol, no tocar SQLite/configuración, no instalar en hosts ajenos,
no ejecutar workflows durante la revisión de la PR. El merge tampoco prueba
que Reports haya sido desplegado en gway-001.
