#!/usr/bin/env python3
"""
VPN Bot Watchdog — мониторинг живости @Poliakarbot (vpn-seller-bot).

Проблема (pitfall #46): aiogram при Unauthorized НЕ падает, а ретраит бесконечно.
`systemctl is-active` показывает active (running), но бот мёртв — продажи встали.
Этот watchdog проверяет РЕАЛЬНУЮ живость: polling-лог на Unauthorized/Failed to fetch.

Проверяет:
1. systemctl is-active vpn-seller-bot (system-level)
2. polling-лог за последние 30 мин на Unauthorized / TelegramConflictError
3. Failed to fetch updates подряд (сетевые флуктуации → ретрай, не смерть)

Алерт в Telegram админу (@poliakarm) при: inactive, Unauthorized, или >N Failed.

Cron (root, каждый час):
    0 * * * * python3 /home/openclaw/.hermes/scripts/vpn-bot-watch.py
"""

import json
import os
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

SERVICE = "vpn-seller-bot"                      # system-level unit
ADMIN_CHAT_ID = "319665243"                     # @poliakarm (основной)
ENV_PATH = Path("/home/openclaw/.hermes/.env")  # TELEGRAM_BOT_TOKEN (Hermes-бот)
STATE_FILE = Path("/home/openclaw/.hermes/logs/vpn-bot-watch.state")
LOG_FILE = Path("/home/openclaw/.hermes/logs/vpn-bot-watch.log")

LOOKBACK_MINUTES = 30
ALERT_COOLDOWN_SEC = 3600   # не чаще 1 раза в час
FAILED_FETCH_LIMIT = 10     # >10 Failed to fetch за окно = алерт


def log(msg: str):
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    line = f"[{ts}] {msg}"
    LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
    with open(LOG_FILE, "a") as f:
        f.write(line + "\n")
    print(line)


def run(cmd: list, timeout=15) -> tuple[str, int]:
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        return (r.stdout + r.stderr).strip(), r.returncode
    except Exception as e:
        return str(e), 1


def get_token() -> str:
    if ENV_PATH.exists():
        for line in ENV_PATH.read_text().splitlines():
            line = line.strip()
            if line.startswith("TELEGRAM_BOT_TOKEN="):
                return line.split("=", 1)[1].strip().strip('"').strip("'")
    return os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()


def send_alert(text: str) -> bool:
    token = get_token()
    if not token:
        log("⚠️ нет TELEGRAM_BOT_TOKEN — алерт не отправлен")
        return False
    payload = json.dumps({
        "chat_id": ADMIN_CHAT_ID,
        "text": text,
        "disable_web_page_preview": True,
    })
    try:
        r = subprocess.run(
            ["curl", "-s", "-m", "15",
             "-H", "Content-Type: application/json",
             "-d", payload,
             f"https://api.telegram.org/bot{token}/sendMessage"],
            capture_output=True, text=True, timeout=20,
        )
        out = r.stdout.strip()
        ok = '"ok":true' in out
        if not ok:
            log(f"⚠️ sendMessage failed: {out[:200]}")
        return ok
    except Exception as e:
        log(f"⚠️ sendMessage exception: {e}")
        return False


def load_state() -> dict:
    try:
        if STATE_FILE.exists():
            return json.loads(STATE_FILE.read_text())
    except Exception:
        pass
    return {}


def save_state(state: dict):
    STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    STATE_FILE.write_text(json.dumps(state))


def check_bot() -> dict:
    """Вернуть {alive: bool, reason: str}."""
    # 1. Сервис жив?
    out, code = run(["sudo", "systemctl", "is-active", SERVICE])
    active = (out.strip() == "active")
    if not active:
        return {"alive": False, "reason": f"service is '{out.strip()}'"}

    # 2. Polling-лог за окно
    since = f"{LOOKBACK_MINUTES} min ago"
    out, _ = run(["sudo", "journalctl", "-u", SERVICE, "--since", since,
                  "--no-pager"])
    low = out

    if "TelegramUnauthorizedError" in low or "Unauthorized" in low:
        return {"alive": False, "reason": "TelegramUnauthorizedError (токен отозван/мёртв)"}

    if "TelegramConflictError" in low:
        return {"alive": False, "reason": "TelegramConflictError (второй инстанс бота)"}

    failed_count = low.count("Failed to fetch updates")
    if failed_count > FAILED_FETCH_LIMIT:
        return {"alive": False,
                "reason": f"{failed_count}× Failed to fetch updates (сеть к Telegram нестабильна)"}

    return {"alive": True, "reason": "ok"}


def main():
    result = check_bot()
    now = time.time()
    state = load_state()

    if result["alive"]:
        # Жив — сбрасываем cooldown-метку
        if state.get("last_alert_ts"):
            state.pop("last_alert_ts", None)
            state.pop("last_alert_reason", None)
            save_state(state)
            log(f"✅ бот жив ({result['reason']}) — cooldown сброшен")
        return 0

    # Мёртв — алерт с cooldown
    reason = result["reason"]
    last_ts = state.get("last_alert_ts", 0)
    last_reason = state.get("last_alert_reason", "")

    if now - last_ts < ALERT_COOLDOWN_SEC and last_reason == reason:
        log(f"🔕 бот мёртв ({reason}) — в cooldown, алерт пропущен")
        return 0

    text = f"🚨 VPN-бот @Poliakarbot неживой!\nПричина: {reason}\n\n" \
           f"Диагностика:\n" \
           f"sudo systemctl status {SERVICE}\n" \
           f"sudo journalctl -u {SERVICE} -n 30 --no-pager"
    ok = send_alert(text)
    log(f"{'📤 алерт отправлен' if ok else '⚠️ алерт НЕ ушёл'}: {reason}")

    state["last_alert_ts"] = now
    state["last_alert_reason"] = reason
    save_state(state)
    return 0


if __name__ == "__main__":
    sys.exit(main())
