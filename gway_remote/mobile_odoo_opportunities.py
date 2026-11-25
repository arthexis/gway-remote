"""Read-only opportunity projection; no partner-only quotation matching."""
import json
import re
from html import unescape
from .mobile_odoo_quotations import _run

def _query(model, domain, fields, limit, offset=0):
    raw = _run("odoo-domain", ["--model", model, "--domain", json.dumps(domain),
               "--fields", fields, "--limit", str(limit), "--offset", str(offset), "--order", "id asc"])
    try:
        rows = json.loads(raw)
        if type(rows) is not list or len(rows) > limit or any(type(r) is not dict for r in rows):
            raise ValueError()
        return rows
    except (ValueError, TypeError):
        raise RuntimeError("odoo_response_invalid") from None

def _rel(row, field):
    value = row.get(field)
    return value[0] if isinstance(value, list) and len(value) == 2 and type(value[0]) is int else None

def _text(row, field):
    value = row.get(field)
    return value.strip() if isinstance(value, str) else ""

def _request_type(description):
    # Imported CRM descriptions start with a verified normalized priority and type.
    text = unescape(re.sub(r"<[^>]*>", "", description)).strip()
    match = re.match(r"^(?:Urgente|Alta|Normal|Baja)\s+-\s+(Nueva|Desmontado y Montado)\s+-\s+", text, re.I)
    if not match:
        return ""
    return "new" if match[1].lower() == "nueva" else "remove_and_install"

def search(arguments):
    if type(arguments) is not dict or set(arguments) - {"page", "limit"}:
        raise ValueError("invalid_arguments")
    page, limit = arguments.get("page", 1), arguments.get("limit", 10)
    if type(page) is not int or not 1 <= page <= 1000 or type(limit) is not int or not 1 <= limit <= 30:
        raise ValueError("invalid_pagination")
    leads = _query("crm.lead", [["type", "=", "opportunity"], ["active", "=", True], ["probability", "<", 100]],
                   "id,name,partner_id,priority,description", limit + 1, (page - 1) * limit)
    rows = []
    for lead in leads[:limit]:
        ident = lead.get("id")
        if type(ident) is not int or ident <= 0:
            raise RuntimeError("odoo_response_invalid")
        partner_id = _rel(lead, "partner_id")
        orders = _query("sale.order", [["opportunity_id", "=", ident], ["state", "!=", "cancel"]],
                        "id,name,state", 2)
        # Multiple live quotes require explicit current-quote resolution.
        if len(orders) > 1:
            raise RuntimeError("odoo_current_quotation_ambiguous")
        order = orders[0] if orders else {}
        state = _text(order, "state")
        if state in ("sent", "sale", "done"):
            continue
        if state not in ("", "draft"):
            raise RuntimeError("odoo_response_invalid")
        partner = {}
        vehicle = {}
        ticket = re.match(r"^Porsche #([0-9]+): ", _text(lead, "name"))
        if partner_id:
            partners = _query("res.partner", [["id", "=", partner_id]],
                              "id,name,phone,mobile,street,street2,city,state_id,zip,country_id", 1)
            partner = partners[0] if partners else {}
            if ticket:
                vehicles = _query("gelectriic.customer.vehicle", [["partner_id", "=", partner_id],
                                  ["porsche_ticket", "=", ticket.group(1)]], "id,model,vin", 2)
                if len(vehicles) == 1:
                    vehicle = vehicles[0]
        address = [_text(partner, k) for k in ("street", "street2", "city", "zip")]
        for key in ("state_id", "country_id"):
            val = partner.get(key)
            if isinstance(val, list) and len(val) == 2 and isinstance(val[1], str):
                address.append(val[1])
        rows.append({"id": ident, "disposition": "pending",
                     "customer": _text(partner, "name"),
                     "phone": _text(partner, "phone") or _text(partner, "mobile"),
                     "complete_address": ", ".join(filter(None, address)),
                     "priority": {"3": "Urgente", "2": "Alta", "1": "Normal"}.get(_text(lead, "priority"), ""),
                     "request_type": _request_type(_text(lead, "description")), "vehicle_model": _text(vehicle, "model"), "vin": _text(vehicle, "vin"),
                     "consent_url": None, "quotation_name": _text(order, "name") or None,
                     "quotation_state": state or None})
    return {"opportunities": rows, "has_next": len(leads) > limit}
