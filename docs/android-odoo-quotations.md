# Odoo quotations in GWay Remote Android

The **Cotizaciones** home panel searches quotations by folio or customer and
downloads the official Odoo PDF to any location selected through Android's
system document picker. The picker suggests the quotation's exact Odoo name,
such as `S30958 Subestación 1.pdf`. Nothing is confirmed, sent or invoiced.

## Data path

Android uses the existing HTTPS endpoint and bearer token; no Odoo credentials
are stored on the device. The fixed `odoo-quotations` read-only mobile command
runs the already-installed `~/Repos/odoo-gelectriic/bin/odoo-domain` on
gway-001. It returns at most 30 draft/sent quotations.

The authenticated binary route
`GET /api/v1/odoo/quotations/{numeric_id}/pdf` invokes the existing
`odoo-quotation-pdf` using the **quotation** Bastion profile on gway-001.
The official report is created in a private temporary folder, loaded within
a strict size limit, returned as `application/pdf` with RFC5987
`Content-Disposition`, then removed from the server's temporary folder.
The Android app uses its own authenticated request, not DownloadManager
(which would expose the bearer to another component). It validates the
server-supplied filename, MIME, size, header and EOF before reporting success.

## Deployment dependencies

1. `odoo-gelectriic` O4 CLI must be installed on gway-001 with the
   `quotation` profile in its verified Bastion key. The `arthe` user
   running the mobile API must have read access to this profile.
2. Deploy the GWay Remote Python backend update to gway-001 and restart the
   existing **user** mobile API service
   `gway-remote-mobile-api.service`. Keep its existing
   `10.90.0.2:8765` WireGuard bind, bearer file, and TLS routing.
3. On the HTTPS gateway, stage the updated
   `deploy/nginx/gway-remote-locations.conf` snippet using the existing
   `scripts/stage-https-gateway.sh` procedure, then validate `nginx -t`
   before reload. The new regex location permits only GET for a bounded
   numeric quotation ID and passes the bearer header to gway-001.
4. Install the newly signed Android release produced after the PR is merged,
   then enter **Cotizaciones**, search by folio or customer, choose
   **Descargar PDF** and pick the Android storage folder.

## Acceptance

The pre-existing Odoo quotation ID **857** is
`S30958 Subestación 1`. The server's quotation search returns it when
searching for `Subestación`, and its official PDF is approximately 49.6 KB
and uses `es_MX`. Mobile acceptance requires checking that the resulting
PDF on Android is named `S30958 Subestación 1.pdf`, opens normally, and that
an unauthorized request returns 401 without report content.

The feature intentionally has no PDF sharing URL, Odoo edit operation, or
ability to request arbitrary files on the gateway.
