"""Read-only opportunity projection; no partner-only quotation matching."""
import json
import re
import os
import stat
from pathlib import Path
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

def _porsche_ticket(lead):
    name = re.match(r"^Porsche #([0-9]{1,12}): ", _text(lead, "name"))
    description = unescape(re.sub(r"<[^>]*>", "", re.sub(r"<br\s*/?>", "\n", _text(lead, "description"), flags=re.I))).strip()
    markers = re.findall(r"(?m)^Porsche Ticket: ([0-9]{1,12})[ \t]*$", description)
    tickets = set(markers) | ({name[1]} if name else set())
    return next(iter(tickets)) if len(tickets) == 1 else None

def _stage_name(lead):
    stage = lead.get("stage_id")
    return stage[1].strip() if _rel(lead, "stage_id") and isinstance(stage[1], str) else None

def _request_type(description):
    # Imported CRM descriptions start with a verified normalized priority and type.
    text = unescape(re.sub(r"<[^>]*>", "", description)).strip()
    match = re.match(r"^(?:Urgente|Alta|Normal|Baja)\s+-\s+(Nueva|Desmontado y Montado)\s+-\s+", text, re.I)
    if not match:
        return ""
    return "new" if match[1].lower() == "nueva" else "remove_and_install"

def _consent_bindings():
    """Operator-maintained evidence only; never infer consent from a customer."""
    path = Path.home() / ".local/state/gway-remote/odoo-consents.json"
    try:
        fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    except FileNotFoundError:
        return {}
    try:
        with os.fdopen(fd, "r", encoding="utf-8") as stream:
            info = os.fstat(stream.fileno())
            if not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid() or info.st_mode & 0o077 or info.st_size > 262144:
                raise ValueError("unsafe evidence store")
            data = json.load(stream)
            if type(data) is not dict:
                raise ValueError("invalid evidence store")
            return data
    except (OSError, ValueError, UnicodeError):
        raise RuntimeError("odoo_consent_store_invalid") from None

def _consent_url(bindings, ident, partner_id, ticket):
    record = bindings.get(str(ident))
    if not ticket or type(partner_id) is not int or type(record) is not dict:
        return None
    if type(record.get("partner_id")) is not int or record["partner_id"] != partner_id or record.get("ticket") != ticket:
        return None
    file_id = record.get("file_id")
    if not isinstance(file_id, str) or not re.fullmatch(r"[A-Za-z0-9_-]{10,150}", file_id):
        return None
    return "https://drive.google.com/file/d/" + file_id + "/view"

def search(arguments):
    if type(arguments) is not dict or set(arguments) - {"page", "limit"}:
        raise ValueError("invalid_arguments")
    page, limit = arguments.get("page", 1), arguments.get("limit", 10)
    if type(page) is not int or not 1 <= page <= 1000 or type(limit) is not int or not 1 <= limit <= 30:
        raise ValueError("invalid_pagination")
    leads = _query("crm.lead", [["type", "=", "opportunity"], ["active", "=", True]],
                   "id,name,partner_id,priority,description,probability,stage_id", limit + 1, (page - 1) * limit)
    bindings = _consent_bindings()
    # Preserve raw lead pagination and quote association. All related reads
    # are bounded by the page size, never by the number of customers.
    active = {}
    seen = set()
    for lead in leads[:limit]:
        ident = lead.get("id")
        if type(ident) is not int or ident <= 0 or ident in seen:
            raise RuntimeError("odoo_response_invalid")
        seen.add(ident)
        if lead.get("probability", 0) != 100:
            active[ident] = lead

    orders_by_lead = {}
    if active:
        orders = _query("sale.order", [["opportunity_id", "in", list(active)],
                        ["state", "!=", "cancel"]], "id,name,state,opportunity_id", len(active) + 1)
        for order in orders:
            ident = _rel(order, "opportunity_id")
            if ident not in active:
                raise RuntimeError("odoo_response_invalid")
            # A saturated result necessarily contains duplicate associations.
            # Never select a current quote based on ordering or partner.
            if ident in orders_by_lead:
                raise RuntimeError("odoo_current_quotation_ambiguous")
            orders_by_lead[ident] = order
    pending = []
    for ident, lead in active.items():
        order = orders_by_lead.get(ident, {})
        state = _text(order, "state")
        if state in ("sent", "sale", "done"):
            continue
        if state not in ("", "draft"):
            raise RuntimeError("odoo_response_invalid")
        pending.append((ident, lead, order, state, _rel(lead, "partner_id"), _porsche_ticket(lead)))

    partner_ids = sorted({partner_id for _, _, _, _, partner_id, _ in pending if partner_id})
    partners_by_id = {}
    if partner_ids:
        partners = _query("res.partner", [["id", "in", partner_ids]],
                          "id,name,phone,mobile,street,street2,city,state_id,zip,country_id", len(partner_ids))
        for partner in partners:
            ident = partner.get("id")
            if type(ident) is not int or ident not in partner_ids or ident in partners_by_id:
                raise RuntimeError("odoo_response_invalid")
            partners_by_id[ident] = partner

    pairs = sorted({(partner_id, ticket) for _, _, _, _, partner_id, ticket in pending
                    if partner_id and ticket})
    vehicles_by_pair = {}
    if pairs:
        # An OR of exact (partner, ticket) conjunctions, not a Cartesian
        # product of partner IDs and ticket numbers. Keep two matches distinct
        # so an ambiguous vehicle remains unavailable as before.
        domain = ["|"] * (len(pairs) - 1)
        for partner_id, ticket in pairs:
            domain.extend(["&", ["partner_id", "=", partner_id], ["porsche_ticket", "=", ticket]])
        vehicle_limit = 2 * len(pairs) + 1
        vehicles = _query("gelectriic.customer.vehicle", domain,
                          "id,partner_id,porsche_ticket,model,vin", vehicle_limit)
        if len(vehicles) == vehicle_limit:
            # A truncated batch cannot establish uniqueness of every pair.
            raise RuntimeError("odoo_vehicle_batch_incomplete")
        allowed_pairs = set(pairs)
        for vehicle in vehicles:
            pair = (_rel(vehicle, "partner_id"), _text(vehicle, "porsche_ticket"))
            if pair not in allowed_pairs:
                raise RuntimeError("odoo_response_invalid")
            vehicles_by_pair.setdefault(pair, []).append(vehicle)

    rows = []
    for ident, lead, order, state, partner_id, ticket in pending:
        partner = partners_by_id.get(partner_id, {})
        vehicles = vehicles_by_pair.get((partner_id, ticket), [])
        vehicle = vehicles[0] if len(vehicles) == 1 else {}
        address = [_text(partner, k) for k in ("street", "street2", "city", "zip")]
        for key in ("state_id", "country_id"):
            val = partner.get(key)
            if isinstance(val, list) and len(val) == 2 and isinstance(val[1], str):
                address.append(val[1])
        rows.append({"id": ident, "disposition": "pending",
                     "customer": _text(partner, "name"),
                     "stage_id": _rel(lead, "stage_id"), "stage_name": _stage_name(lead),
                     "phone": _text(partner, "phone") or _text(partner, "mobile"),
                     "complete_address": ", ".join(filter(None, address)),
                     "priority": {"3": "Urgente", "2": "Alta", "1": "Normal"}.get(_text(lead, "priority"), ""),
                     "request_type": _request_type(_text(lead, "description")), "vehicle_model": _text(vehicle, "model"), "vin": _text(vehicle, "vin"),
                     "consent_url": _consent_url(bindings, ident, partner_id, ticket), "quotation_name": _text(order, "name") or None,
                     "quotation_state": state or None})
    return {"opportunities": rows, "has_next": len(leads) > limit}
