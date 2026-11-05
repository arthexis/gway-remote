"""Odoo mobile API bridge: strict input, fixed CLIs, no credential disclosure."""
import io
import json
from pathlib import Path
from unittest.mock import Mock

import pytest

from gway_remote import mobile_odoo_quotations as odoo


def test_search_is_read_only_and_bounded(monkeypatch):
    calls = []
    def runner(executable, args, timeout=30):
        calls.append((executable, args))
        return json.dumps([
            {"id":857,"name":"S30958 Subestación 1","state":"draft",
             "partner_id":[594,"Subestación 1"],"date_order":"2026-11-04 21:30:00",
             "amount_total":364240.0,"currency_id":[33,"MXN"]},
            {"id":856,"name":"S30957","state":"sale",
             "partner_id":[55,"Other"],"date_order":False,
             "amount_total":1,"currency_id":[33,"MXN"]},
        ])
    monkeypatch.setattr(odoo, "_run", runner)
    r = odoo.search({"query":"Subestación", "limit":10})
    assert r["count"]==1
    assert r["quotations"][0]["name"]=="S30958 Subestación 1"
    assert calls[0][0]=="odoo-domain"
    assert calls[0][1][0:2]==["--model","sale.order"]
    assert calls[0][1][-2:]==["--limit","10"]
    assert "Subestación" in calls[0][1][3]


@pytest.mark.parametrize("arguments", [
    {"query":"x"*81}, {"query":"bad\nnewline"}, {"query":3},
    {"limit":0}, {"limit":100}, {"limit":True}, {"query":"","extra":1},
    ["str"]
])
def test_search_rejects_unbounded_input(arguments):
    with pytest.raises(ValueError):
        odoo.search(arguments)


@pytest.mark.parametrize("order_id", [0, -1, True, "857", 10**11])
def test_download_rejects_bad_ids(order_id):
    with pytest.raises(ValueError):
        odoo.download(order_id)


def test_pdf_download_validates_bytes_and_cleans_files(monkeypatch):
    output = b"%PDF-1.4\n" + b"a"*1500 + b"%%EOF"
    def fake_runner(executable, args, timeout=30):
        assert executable=="odoo-quotation-pdf"
        assert args[:2]==["--order-id","857"]
        assert args[2:4]==["--credential-profile","quotation"]
        path=Path(args[-1])
        (path/"S30958 Subestación 1.pdf").write_bytes(output)
        return "{}"
    monkeypatch.setattr(odoo, "_run", fake_runner)
    filename, data = odoo.download(857)
    assert filename == "S30958 Subestación 1.pdf"
    assert data == output


def test_fails_closed_on_bad_pdf(monkeypatch):
    def fake_runner(executable, args, timeout=30):
        (Path(args[-1])/"invoice.pdf").write_bytes(b"<html>" * 300)
        return "{}"
    monkeypatch.setattr(odoo, "_run", fake_runner)
    with pytest.raises(RuntimeError,match="odoo_pdf_invalid"):
        odoo.download(857)


def test_headers_preserve_spanish_name():
    value=odoo.filename_headers("S30958 Subestación 1.pdf")
    assert "filename*=UTF-8''" in value
    assert "Subestaci%C3%B3n%201.pdf" in value
    assert "\r" not in value and "\n" not in value
    with pytest.raises(ValueError):
        odoo.filename_headers("bad\r\nname.pdf")


def test_no_shell_invocation(monkeypatch):
    class Done:
        returncode=0
        stdout="[]"
        stderr=""
    called=[]
    def run(command, **kwargs):
        called.append((command,kwargs))
        return Done()
    monkeypatch.setattr(odoo,"ROOT",Path("/mock/odoo/bin"))
    monkeypatch.setattr(Path,"is_file",lambda self: True)
    monkeypatch.setattr(odoo.subprocess,"run",run)
    assert odoo._run("odoo-domain", ["--model","sale.order"])=="[]"
    assert called[0][0][0]=="/mock/odoo/bin/odoo-domain"
    assert called[0][1]["timeout"]==30
    assert "shell" not in called[0][1]
