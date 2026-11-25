# Oportunidades Android — draft contract

The current Odoo instance returned `Object crm.lead doesn't exist`. The Android draft must **not** be merged/released until Odoo native CRM is operational and the provider has an authenticated, paginated, reviewed read endpoint. Related: arthexis/odoo-gelectriic#100 and #102.

Proposed mobile API command: `odoo-opportunities` on the existing authenticated `/api/v1/execute` read path. Arguments: integer page >= 1, limit 1..30. Response: `result.opportunities` and boolean `result.has_next`.

Each item:
- positive unique native opportunity `id`, `disposition` (pending/lost/cancelled/closed)
- customer, phone, complete_address, priority, vehicle_model, vin (strings, blank when not verified)
- request_type (new / remove_and_install, otherwise unknown)
- consent_url (canonical private Drive file view URL, or null)
- quotation_name, quotation_state (null or verified current native sale.order linked to this specific opportunity; draft/sent/sale/done/cancel)

Selection belongs to Odoo. The provider must resolve the actual active/current quotation relation, never infer it by partner, template, latest quote of the customer, or a similar name. Close the pending display only for a linked sent or subsequent sales state or explicitly closed/lost/cancelled opportunity. Cancelled quotation alone does not close a pending opportunity. Confirm the precise real schema and authoritative sent-state behavior before binding the backend.

Do not store actual client data, signed consents, tokens, source email or Drive URLs in Git. Associate private file ID/verified canonical URL with the opportunity in the reviewed intake/evidence flow. Do not change Drive sharing. The mobile app opens only a canonical HTTPS Drive file URL through the user's normal Android handler without forwarding the bearer.

The Android draft is testable with synthetic responses. Production CRM installation, secure intake of consent documents, migration/association, backend ACL/endpoint implementation, integration tests, physical canary and production deployment are explicitly pending. Do not add a second CRM in Sheets or infer existing opportunities from historical customers. Clipboard payload is the exact line value only, marked sensitive; missing values cannot be copied. No logging/persistence of the displayed data.
