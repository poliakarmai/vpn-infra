"""Тесты admin_key.py — то, чем реально выдают ключи на проде.

Прод не трогаем: БД, конфиг Xray и бинарник xray подменяются на временные.
Главный регресс — dry-run обязан не писать в БД (инвариант #6 в AGENTS.md):
раньше grant_subscription() вызывался до проверки флага и оставлял
активную подписку-мусор, которая попадала в config.json при rebuild.
"""
import importlib
import json
import sqlite3
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

SCHEMA = """
CREATE TABLE users (tg_id INTEGER PRIMARY KEY, created_at INTEGER NOT NULL);
CREATE TABLE subscriptions (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  tg_id INTEGER NOT NULL, uuid TEXT NOT NULL,
  created_at INTEGER NOT NULL, expires_at INTEGER NOT NULL, active INTEGER NOT NULL
);
"""


@pytest.fixture
def ak(tmp_path, monkeypatch):
    """Свежий модуль admin_key с временными БД/конфигом/бинаром."""
    db_path = tmp_path / "vpn_seller.sqlite"
    con = sqlite3.connect(db_path)
    con.executescript(SCHEMA)
    con.commit()
    con.close()

    cfg = tmp_path / "config.json"
    cfg.write_text(json.dumps({
        "inbounds": [{
            "port": 4443,
            "settings": {"clients": []},
            "streamSettings": {"realitySettings": {
                "serverNames": ["www.cloudflare.com"], "shortIds": ["abc123"]}},
        }],
    }))
    tmpl = tmp_path / "config.template.json"
    tmpl.write_text(json.dumps({"inbounds": [{"port": 4443, "settings": {"clients": []}}]}))
    xray_bin = tmp_path / "xray"
    xray_bin.write_text("#!/bin/sh\nexit 0\n")
    xray_bin.chmod(0o755)

    monkeypatch.setenv("DB_PATH", str(db_path))
    monkeypatch.setenv("XRAY_CONFIG_PATH", str(cfg))
    monkeypatch.setenv("XRAY_TEMPLATE_PATH", str(tmpl))
    monkeypatch.setenv("XRAY_BIN", str(xray_bin))
    monkeypatch.setenv("SERVER_IP", "2.27.48.142")
    monkeypatch.setenv("VLESS_PBK", "PUBKEY")

    sys.modules.pop("admin_key", None)
    return importlib.import_module("admin_key")


def subs(mod):
    con = sqlite3.connect(mod.DB_PATH)
    try:
        return con.execute("SELECT tg_id, uuid, active, expires_at FROM subscriptions").fetchall()
    finally:
        con.close()


def test_dry_run_does_not_touch_db(ak, monkeypatch, capsys):
    def boom(*a, **kw):
        raise AssertionError("dry-run не должен вызывать rebuild_xray")

    monkeypatch.setattr(ak, "rebuild_xray", boom)
    monkeypatch.setattr(ak, "grant_subscription", boom)
    monkeypatch.setattr(sys, "argv", ["admin_key.py", "319665243", "30", "--dry-run"])

    ak.main()

    assert subs(ak) == [], "dry-run записал подписку в БД"
    out = capsys.readouterr().out
    assert "[DRY RUN]" in out
    assert "vless://" in out, "dry-run не напечатал ссылку"


def test_dry_run_still_needs_server_ip(ak, monkeypatch):
    monkeypatch.setattr(ak, "SERVER_IP", "")
    monkeypatch.setattr(sys, "argv", ["admin_key.py", "1", "30", "--dry-run"])
    with pytest.raises(SystemExit) as e:
        ak.main()
    assert e.value.code == 1


def test_negative_days_rejected(ak, monkeypatch):
    monkeypatch.setattr(sys, "argv", ["admin_key.py", "1", "-5"])
    with pytest.raises(SystemExit) as e:
        ak.main()
    assert e.value.code == 2
    assert subs(ak) == []


def test_grant_creates_active_subscription(ak):
    info = ak.grant_subscription(319665243, 30, "test")
    rows = subs(ak)
    assert len(rows) == 1
    tg_id, uuid, active, expires = rows[0]
    assert (tg_id, uuid, active) == (319665243, info["uuid"], 1)
    assert expires == info["expires_at"]
    assert abs(info["expires_at"] - info["expires_at"] // 86400 * 86400) < 90000  # sanity


def test_grant_does_not_deactivate_other_keys(ak):
    ak.grant_subscription(111, 30)
    ak.grant_subscription(111, 90)
    rows = subs(ak)
    assert len(rows) == 2
    assert all(r[2] == 1 for r in rows), "админский ключ погасил соседний"


def test_active_uuids_skips_expired_and_inactive(ak):
    now = int(ak.time.time())
    con = sqlite3.connect(ak.DB_PATH)
    con.execute("INSERT INTO subscriptions (tg_id, uuid, created_at, expires_at, active) VALUES (?,?,?,?,?)",
                (1, "live", now, now + 3600, 1))
    con.execute("INSERT INTO subscriptions (tg_id, uuid, created_at, expires_at, active) VALUES (?,?,?,?,?)",
                (2, "expired", now - 7200, now - 3600, 1))
    con.execute("INSERT INTO subscriptions (tg_id, uuid, created_at, expires_at, active) VALUES (?,?,?,?,?)",
                (3, "off", now, now + 3600, 0))
    con.commit()
    con.close()

    assert ak.list_active_uuids() == ["live"]


def test_rebuild_writes_clients_and_deactivates_expired(ak, monkeypatch):
    now = int(ak.time.time())
    con = sqlite3.connect(ak.DB_PATH)
    con.execute("INSERT INTO subscriptions (tg_id, uuid, created_at, expires_at, active) VALUES (?,?,?,?,?)",
                (1, "keep-me", now, now + 86400, 1))
    con.execute("INSERT INTO subscriptions (tg_id, uuid, created_at, expires_at, active) VALUES (?,?,?,?,?)",
                (2, "old", now - 999, now - 1, 1))
    con.commit()
    con.close()

    calls = []

    class R:
        returncode = 0
        stderr = stdout = ""

    monkeypatch.setattr(ak.subprocess, "run", lambda *a, **kw: calls.append(a[0]) or R())

    ak.rebuild_xray()

    cfg = json.loads(Path(ak.XRAY_CONFIG_PATH).read_text())
    clients = cfg["inbounds"][0]["settings"]["clients"]
    assert [c["id"] for c in clients] == ["keep-me"]
    expired = sqlite3.connect(ak.DB_PATH)
    active = expired.execute("SELECT active FROM subscriptions WHERE uuid='old'").fetchone()[0]
    expired.close()
    assert active == 0, "истёкшая подписка осталась активной"


def test_rebuild_rolls_back_on_bad_config(ak, monkeypatch):
    ak.grant_subscription(1, 30)
    before = Path(ak.XRAY_CONFIG_PATH).read_text()

    class R:
        returncode = 1
        stderr = "bad config"
        stdout = ""

    monkeypatch.setattr(ak.subprocess, "run", lambda *a, **kw: R())

    with pytest.raises(SystemExit):
        ak.rebuild_xray()

    assert Path(ak.XRAY_CONFIG_PATH).read_text() == before, "конфиг не откатился после провала теста"


def test_vless_link_uses_config_port_and_sni(ak):
    link = ak.build_vless_link("11111111-2222-3333-4444-555555555555", "test")
    assert link.startswith("vless://11111111-2222-3333-4444-555555555555@2.27.48.142:4443?")
    assert "sni=www.cloudflare.com" in link
    assert "pbk=PUBKEY" in link
    assert "sid=abc123" in link
    assert link.endswith("#test")
