#!/usr/bin/env python3
"""Разовая рассылка по базе VPN-бота — сообщить о Stars-оплате и триале."""
import json
import sqlite3
import sys
import time
import urllib.request
import urllib.error

ENV = "/opt/vpn-seller-bot/.env"
DB = "/opt/vpn-seller-bot/data/vpn_seller.sqlite"
STATE = "/home/openclaw/.hermes/logs/vpn-broadcast.sent"

# Исключения: админ, второй аккаунт, тестовые, без chat_id
EXCLUDE = {319665243, 5529208670, 123456789, 111222333}

TEXT = (
    "👋 Привет! VPN-сервис @Poliakarbot обновился:\n\n"
    "⭐ Оплата звёздами Telegram — без внешних кошельков\n"
    "🎁 Бесплатный триал 3 дня\n"
    "🔒 VLESS, WireGuard, TG-прокси — от $0.5\n\n"
    "Жми /start чтобы посмотреть тарифы"
)


def get_token():
    for line in open(ENV):
        line = line.strip()
        if line.startswith("TELEGRAM_BOT_TOKEN="):
            return line.split("=", 1)[1].strip().strip('"').strip("'")
    return ""


def send(token, chat_id, text):
    payload = json.dumps({"chat_id": chat_id, "text": text,
                          "disable_web_page_preview": True}).encode()
    req = urllib.request.Request(
        f"https://api.telegram.org/bot{token}/sendMessage",
        data=payload, headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=15) as r:
            return True, json.loads(r.read()).get("ok", False)
    except urllib.error.HTTPError as e:
        body = e.read().decode()[:120]
        if e.code == 403:
            return False, "blocked/forbidden"
        if e.code == 400:
            return False, "bad request (нет чата?)"
        return False, f"HTTP {e.code}: {body}"
    except Exception as e:
        return False, str(e)[:80]


def main():
    token = get_token()
    if not token:
        print("нет токена"); return 1

    conn = sqlite3.connect(DB)
    conn.row_factory = sqlite3.Row
    rows = conn.execute(
        "SELECT tg_id, COALESCE(main_chat_id, tg_id) AS chat_id FROM users"
    ).fetchall()
    conn.close()

    # Дедупликация: пропустить уже отправленных (стейт-файл)
    import os
    sent = set()
    if os.path.exists(STATE):
        sent = set(int(x) for x in open(STATE).read().split() if x.isdigit())

    targets = [r for r in rows if r["tg_id"] not in EXCLUDE
               and r["tg_id"] not in sent]
    print(f"Целей всего: {len(rows)}, осталось отправить: {len(targets)}")

    ok = blocked = err = 0
    for i, r in enumerate(targets, 1):
        ok_, msg = send(token, r["chat_id"], TEXT)
        if ok_:
            ok += 1
            print(f"[{i}/{len(targets)}] ✅ {r['tg_id']}")
            with open(STATE, "a") as f:
                f.write(f"{r['tg_id']}\n")
        else:
            if "blocked" in str(msg):
                blocked += 1
                print(f"[{i}/{len(targets)}] 🚫 {r['tg_id']} — {msg}")
            else:
                err += 1
                print(f"[{i}/{len(targets)}] ⚠️ {r['tg_id']} — {msg}")
        time.sleep(1.0)  # анти-flood

    print(f"\nИтог: доставлено={ok} заблокировано={blocked} ошибок={err}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
