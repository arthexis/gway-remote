"""Read-only Odoo quotation catalogue and native PDF bridge for the mobile API.

Bastion credentials remain on gway-001. Only fixed local CLI programs are
invoked; no command strings, paths or report template names are user-supplied.
"""
from __future__ import annotations

import json
import re
import subprocess
import tempfile
from pathlib import Path

ROOT = Path("/opt/odoo-gelectriic/bin")
MAX_PDF = 20 * 1024 * 1024
MAX_RESULTS = 30
MAX_PAGE = 1000
QUERY_LIMIT = 80


def _run(executable, args, timeout=30):
    script = ROOT / executable
    if not script.is_file():
        raise RuntimeError("odoo_cli_unavailable")
    try:
        done = subprocess.run(
            [str(script), *args], timeout=timeout, capture_output=True,
            check=False, text=True)
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise RuntimeError("odoo_cli_unavailable") from exc
    if done.returncode:
        # Never propagate CLI stdout/stderr: Odoo may embed customer or auth data.
        raise RuntimeError("odoo_operation_failed")
    return done.stdout


def _valid_id(order_id):
    if type(order_id) is not int or not 1 <= order_id <= 2_147_483_647:
        raise ValueError("invalid_quotation_id")
    return order_id


def search(arguments):
    if type(arguments) is not dict or set(arguments) - {"query", "limit", "page"}:
        raise ValueError("invalid_arguments")
    query = arguments.get("query", "")
    limit = arguments.get("limit", 10)
    page = arguments.get("page", 1)
    if type(query) is not str or len(query) > QUERY_LIMIT or any(ord(ch) < 32 for ch in query):
        raise ValueError("invalid_quotation_query")
    if type(limit) is not int or not 1 <= limit <= MAX_RESULTS:
        raise ValueError("invalid_quotation_limit")
    if type(page) is not int or not 1 <= page <= MAX_PAGE:
        raise ValueError("invalid_quotation_page")
    query = query.strip()
    # Explicit OR between quotation reference and partner display name.
    quote_states = ["state", "in", ["draft", "sent"]]
    domain = ["&", quote_states, "|", ["name", "ilike", query],
              ["partner_id", "ilike", query]] if query else [quote_states]
    raw = _run("odoo-domain", [
        "--model", "sale.order", "--domain", json.dumps(domain),
        "--fields", "id,name,state,partner_id,date_order,amount_total,currency_id",
        "--order", "date_order desc,id desc", "--limit", str(limit + 1),
        "--offset", str((page - 1) * limit)])
    try:
        records = json.loads(raw)
        if type(records) is not list or len(records) > limit + 1:
            raise ValueError("unexpected Odoo response")
        result = []
        for row in records[:limit]:
            if type(row) is not dict or type(row.get("id")) is not int:
                raise ValueError("unexpected Odoo row")
            if row.get("state") not in ("draft", "sent"):
                continue
            result.append({
                "id": row["id"], "name": row["name"],
                "customer": row.get("partner_id", ["", ""])[1],
                "date": row.get("date_order") or "",
                "total": row.get("amount_total", 0),
                "currency": row.get("currency_id", ["", ""])[1],
                "state": row["state"],
            })
    except (ValueError, KeyError, TypeError, IndexError) as exc:
        raise RuntimeError("odoo_response_invalid") from exc
    return {"quotations": result, "count": len(result), "limit": limit,
            "page": page, "has_next": len(records) > limit}


def _pdf_filename(name):
    if type(name) is not str or not name.strip() or len(name) > 130:
        raise RuntimeError("odoo_pdf_name_invalid")
    if any(ch in name for ch in ("/", "\\", "\r", "\n", "\x00")):
        raise RuntimeError("odoo_pdf_name_invalid")
    return name.strip() + ".pdf"


def download(order_id):
    _valid_id(order_id)
    script = ROOT / "odoo-quotation-pdf"
    if not script.is_file():
        raise RuntimeError("odoo_cli_unavailable")
    with tempfile.TemporaryDirectory(prefix="gway-odoo-pdf-") as directory:
        _run("odoo-quotation-pdf", [
            "--order-id", str(order_id), "--credential-profile", "quotation",
            "--output-dir", directory], timeout=100)
        outputs = list(Path(directory).glob("*.pdf"))
        if len(outputs) != 1:
            raise RuntimeError("odoo_pdf_unavailable")
        path = outputs[0]
        size = path.stat().st_size
        if not 1024 <= size <= MAX_PDF:
            raise RuntimeError("odoo_pdf_invalid")
        document = path.read_bytes()
        if not document.startswith(b"%PDF-") or b"%%EOF" not in document[-2048:]:
            raise RuntimeError("odoo_pdf_invalid")
        return _pdf_filename(path.stem), document


def filename_headers(filename):
    """Content-Disposition with safe ASCII fallback and RFC5987 UTF-8 name."""
    from urllib.parse import quote
    if not filename.endswith(".pdf") or any(ord(c) < 32 for c in filename):
        raise ValueError("invalid_filename")
    plain = re.sub(r"[^A-Za-z0-9_. -]", "_", filename)
    plain = plain.replace('"', "_").replace("\\", "_")
    return f'attachment; filename="{plain}"; filename*=UTF-8\'\'{quote(filename, safe="")}'
