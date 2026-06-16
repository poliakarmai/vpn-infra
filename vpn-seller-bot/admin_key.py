#!/usr/bin/env python3
"""
Admin key generator — выдаёт VLESS-ссылку напрямую, без бота и оплат.
Использование:
  python3 admin_key.py <tg_id> <дни> [--note "комментарий"]
  
Пример:
  python3 admin_key.py 319665243 30
  python3 admin_key.py 319665243 90 --note "админский доступ"
"""

import argparse
import json
import os
import sqlite3
import subprocess
import sys
import time
import uuid
from pathlib import Path

# ── Загрузка .env ──
from dotenv import load_dotenv
load_dotenv(Path(__file__).resolve().parent.parent / ".env")

DB_PATH = os.environ.get("DB_PATH", "./data/vpn_seller.sqlite")
XRAY_CONFIG_PATH = os.environ.get("XRAY_CONFIG_PATH", "/opt/vpn-core/conf/config.json")
XRAY_SERVICE = os.environ.get("XRAY_SERVICE", "vpn-core-xray")
SERVER_IP = os.environ.get("SERVER_IP", "").strip()
VLESS_PORT = int(os.environ.get("VLESS_PORT", "4443"))
VLESS_SNI = os.environ.get("VLESS_SNI", "www.cloudflare.com").strip()
VLESS_FINGERPRINT = os.environ.get("VLESS_FINGERPRINT", "chrome").strip()
VLESS_PBK = os.environ.get("VLESS_PBK", "").strip()
VLESS_SID = os.environ.get("VLESS_SID", "").strip()

def _read_xray_params():
    """Read actual SNI/PBK/SID/port from the running Xray config."""
    try:
        with open(XRAY_CONFIG_PATH) as f:
            cfg = json.load(f)
        inb = cfg["inbounds"][0]
        rs = inb["streamSettings"]["realitySettings"]
        return {
            "sni": rs["serverNames"][0],
            "pbk": VLESS_PBK,  # public key from .env (config has private key)
            "sid": rs["shortIds"][0],
            "port": inb["port"],
        }
    except Exception:
        return {"sni": VLESS_SNI, "pbk": VLESS_PBK, "sid": VLESS_SID, "port": VLESS_PORT}


def db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def build_vless_link(client_uuid: str, name: str = "vpn") -> str:
    import urllib.parse
    xp = _read_xray_params()
    params = {
        "type": "tcp",
        "security": "reality",
        "encryption": "none",
        "sni": xp["sni"],
        "fp": VLESS_FINGERPRINT,
        "pbk": xp["pbk"],
        "sid": xp["sid"],
        "spx": "/",
        "allowInsecure": "1",
    }
    qs = urllib.parse.urlencode(params)
    safe_name = urllib.parse.quote(name)
    return f"vless://{client_uuid}@{SERVER_IP}:{xp['port']}?{qs}#{safe_name}"


def grant_subscription(tg_id: int, days: int, note: str = "") -> dict:
    """Create subscription record and return sub info."""
    now = int(time.time())
    client_uuid = str(uuid.uuid4())
    expires = now + days * 86400

    with db() as conn:
        # Admin keys DON'T deactivate other keys (multi-key support)
        conn.execute(
            "INSERT INTO subscriptions (tg_id, uuid, created_at, expires_at, active) VALUES (?,?,?,?,1)",
            (tg_id, client_uuid, now, expires),
        )
        # Ensure user record exists
        conn.execute(
            "INSERT OR IGNORE INTO users (tg_id, created_at) VALUES (?,?)",
            (tg_id, now),
        )
        conn.commit()

    return {
        "tg_id": tg_id,
        "uuid": client_uuid,
        "days": days,
        "expires_at": expires,
        "note": note,
    }


def list_active_uuids() -> list[str]:
    now = int(time.time())
    with db() as conn:
        rows = conn.execute(
            "SELECT uuid FROM subscriptions WHERE active=1 AND expires_at>?",
            (now,),
        ).fetchall()
        return [r["uuid"] for r in rows]


def rebuild_xray():
    """Rebuild config, validate, reload."""
    # Deactivate expired
    now = int(time.time())
    with db() as conn:
        conn.execute("UPDATE subscriptions SET active=0 WHERE active=1 AND expires_at<=?", (now,))
        conn.commit()

    active = sorted(set(list_active_uuids()))
    clients = [{"id": u, "email": f"sub-{u}"} for u in active]
    if not clients:
        clients = [{"id": "00000000-0000-0000-0000-000000000000", "email": "disabled"}]

    with open("/opt/vpn-core/conf/config.template.json", "r") as f:
        cfg = json.load(f)
    cfg["inbounds"][0]["settings"]["clients"] = clients

    # Atomic write
    tmp = XRAY_CONFIG_PATH + ".tmp"
    bak = XRAY_CONFIG_PATH + ".bak"
    if os.path.exists(XRAY_CONFIG_PATH):
        import shutil
        shutil.copy(XRAY_CONFIG_PATH, bak)

    with open(tmp, "w") as f:
        json.dump(cfg, f, ensure_ascii=False, indent=2)
    os.replace(tmp, XRAY_CONFIG_PATH)

    # Validate
    r = subprocess.run(
        ["/opt/vpn-core/bin/xray", "run", "-test", "-config", XRAY_CONFIG_PATH],
        capture_output=True, text=True, timeout=10,
    )
    if r.returncode != 0:
        # Rollback
        if os.path.exists(bak):
            os.replace(bak, XRAY_CONFIG_PATH)
        print(f"❌ Config test failed: {(r.stderr or r.stdout)[:500]}", file=sys.stderr)
        sys.exit(1)

    # Reload
    subprocess.run(["sudo", "systemctl", "restart", XRAY_SERVICE], check=True, timeout=20)
    # Clean up backup
    if os.path.exists(bak):
        os.remove(bak)


def main():
    parser = argparse.ArgumentParser(description="Admin VPN key generator")
    parser.add_argument("tg_id", type=int, help="Telegram user ID")
    parser.add_argument("days", type=int, help="Days of access")
    parser.add_argument("--note", default="", help="Admin note")
    parser.add_argument("--name", default="vpn", help="Client name in link (default: vpn)")
    parser.add_argument("--dry-run", action="store_true", help="Generate link only, no DB/xray changes")
    args = parser.parse_args()

    if not SERVER_IP:
        print("❌ SERVER_IP not set in .env", file=sys.stderr)
        sys.exit(1)

    sub_info = grant_subscription(args.tg_id, args.days, args.note)
    link = build_vless_link(sub_info["uuid"], args.name)

    if args.dry_run:
        print(f"[DRY RUN] Would grant {args.days}d to tg_id={args.tg_id}")
        print(link)
        return

    rebuild_xray()

    expires_str = time.strftime("%Y-%m-%d %H:%M", time.localtime(sub_info["expires_at"]))
    print(f"tg_id={args.tg_id}")
    print(f"uuid={sub_info['uuid']}")
    print(f"days={args.days}")
    print(f"expires={expires_str}")
    print(f"link={link}")
    if args.note:
        print(f"note={args.note}")


if __name__ == "__main__":
    main()
