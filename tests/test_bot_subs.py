"""Тесты денежного пути bot.py: подписки по типам и идемпотентность выдачи.

Прод не трогаем: БД, Xray и Telegram подменяются. Регресс, который эти тесты
ловят (находки судного дня 08.11.2026):
  * прокси выдавался бесплатно по кнопке — теперь только через счёт;
  * proxy-строка с uuid "proxy_<tg_id>" уезжала в clients VLESS и ломала
    xray -test → список uuid фильтруется по sub_type;
  * оплата VLESS продлевала активную proxy-подписку (нет фильтра sub_type);
  * fulfilled_at ставился после выдачи → двойное начисление дней.
"""
import asyncio
import importlib
import sqlite3
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

LEGACY_SCHEMA = """
CREATE TABLE users (tg_id INTEGER PRIMARY KEY, created_at INTEGER NOT NULL, lang TEXT);
CREATE TABLE subscriptions (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  tg_id INTEGER NOT NULL, uuid TEXT NOT NULL,
  created_at INTEGER NOT NULL, expires_at INTEGER NOT NULL, active INTEGER NOT NULL
);
CREATE TABLE invoices (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  tg_id INTEGER NOT NULL, invoice_id TEXT UNIQUE NOT NULL, asset TEXT, amount REAL,
  status TEXT, created_at INTEGER, paid_at INTEGER, fulfilled_at INTEGER, meta TEXT
);
"""


class FakeBot:
    """Минимальный стенд вместо aiogram.Bot: пишем, что бот отправил."""

    def __init__(self):
        self.sent = []

    async def send_message(self, chat_id, text, **kw):
        self.sent.append((chat_id, text))

    async def send_photo(self, chat_id, photo, **kw):
        self.sent.append((chat_id, "<photo>"))


@pytest.fixture
def bot_mod(tmp_path, monkeypatch):
    monkeypatch.setenv("DB_PATH", str(tmp_path / "db.sqlite"))
    monkeypatch.setenv("SERVER_IP", "2.27.48.142")
    monkeypatch.setenv("VLESS_PBK", "PBK")
    monkeypatch.setenv("VLESS_SID", "SID")
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "")
    monkeypatch.setenv("CRYPTOBOT_TOKEN", "")
    sys.modules.pop("bot", None)
    mod = importlib.import_module("bot")
    mod.init_db()
    return mod


def rows(mod, sql="SELECT tg_id, uuid, sub_type, active FROM subscriptions"):
    con = sqlite3.connect(mod.DB_PATH)
    try:
        return con.execute(sql).fetchall()
    finally:
        con.close()


def test_fresh_db_has_sub_type(bot_mod):
    cols = {r[1] for r in sqlite3.connect(bot_mod.DB_PATH).execute("PRAGMA table_info(subscriptions)")}
    assert "sub_type" in cols


def test_legacy_db_gets_sub_type_migration(tmp_path, monkeypatch):
    db = tmp_path / "legacy.sqlite"
    con = sqlite3.connect(db)
    con.executescript(LEGACY_SCHEMA)
    con.commit()
    con.close()

    monkeypatch.setenv("DB_PATH", str(db))
    sys.modules.pop("bot", None)
    mod = importlib.import_module("bot")
    mod.init_db()

    cols = {r[1] for r in sqlite3.connect(db).execute("PRAGMA table_info(subscriptions)")}
    assert "sub_type" in cols, "старые БД падали с 'no such column: sub_type'"


def test_list_active_uuids_skips_proxy(bot_mod):
    now = int(bot_mod.time.time())
    with bot_mod.db() as conn:
        conn.execute(
            "INSERT INTO subscriptions (tg_id, uuid, created_at, expires_at, active, sub_type) "
            "VALUES (1,'vless-uuid',?,?,1,'vless')", (now, now + 86400))
        conn.execute(
            "INSERT INTO subscriptions (tg_id, uuid, created_at, expires_at, active, sub_type) "
            "VALUES (1,'',?,?,1,'proxy')", (now, now + 86400))
        conn.commit()

    uuids = bot_mod.list_active_uuids()
    assert uuids == ["vless-uuid"], "uuid прокси не должен попадать в clients Xray"


def test_buying_vless_does_not_extend_proxy(bot_mod):
    now = int(bot_mod.time.time())
    with bot_mod.db() as conn:
        conn.execute(
            "INSERT INTO subscriptions (tg_id, uuid, created_at, expires_at, active, sub_type) "
            "VALUES (7,'',?,?,1,'proxy')", (now, now + 30 * 86400))
        conn.commit()

    sub = bot_mod.create_or_extend_sub(7, "vless-uuid", 30)

    assert sub["uuid"] == "vless-uuid"
    assert sub["sub_type"] == "vless"
    proxy = rows(bot_mod, "SELECT uuid, sub_type, active FROM subscriptions WHERE sub_type='proxy'")
    assert proxy == [("", "proxy", 1)], "VLESS-покупка не должна гасить прокси"


def test_vless_extends_existing_vless(bot_mod):
    now = int(bot_mod.time.time())
    with bot_mod.db() as conn:
        conn.execute(
            "INSERT INTO subscriptions (tg_id, uuid, created_at, expires_at, active, sub_type) "
            "VALUES (8,'same-uuid',?,?,1,'vless')", (now, now + 86400))
        conn.commit()

    sub = bot_mod.create_or_extend_sub(8, "new-uuid", 30)

    assert sub["uuid"] == "same-uuid"
    assert sub["expires_at"] > now + 30 * 86400 - 5


def test_fulfill_proxy_invoice_is_idempotent(bot_mod):
    fake = FakeBot()
    now = int(bot_mod.time.time())
    with bot_mod.db() as conn:
        conn.execute(
            "INSERT INTO invoices (tg_id, invoice_id, asset, amount, status, created_at, meta) "
            "VALUES (9,'inv-1','TON',0.5,'paid',?,?)",
            (now, '{"days": 30, "kind": "proxy"}'))
        conn.commit()

    first = asyncio.run(bot_mod.fulfill_invoice(fake, 9, 9, "inv-1"))
    second = asyncio.run(bot_mod.fulfill_invoice(fake, 9, 9, "inv-1"))

    assert first is True
    assert second is False, "повторная проверка оплаты не должна начислять ещё раз"
    proxy_rows = rows(bot_mod, "SELECT uuid, sub_type, active FROM subscriptions WHERE sub_type='proxy'")
    assert len(proxy_rows) == 1
    assert proxy_rows[0][0] == ""
    assert any("MTProto" in text or "proxy" in text.lower() for _, text in fake.sent)
