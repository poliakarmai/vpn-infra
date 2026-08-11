# Operations Guide

## Deployment Checklist

### Prerequisites
- Python 3.11+
- Xray installed at `/opt/vpn-core/bin/xray`
- WireGuard installed (if offering WG subscriptions)
- systemd
- Domain or VPS with public IP

### Environment Variables

All secrets are loaded from a `.env` file located at the repo root (loaded by both `bot.py` and `admin_key.py`). The README references `.env.example` but that file does not exist in the repository — you must create `.env` from scratch.

The following variables must be configured:

| Variable | Required | Default | Purpose |
|---|---|---|---|
| `TELEGRAM_BOT_TOKEN` | Yes | `""` | Bot token from @BotFather |
| `CRYPTOBOT_TOKEN` | Yes | `""` | CryptoBot API token from @CryptoBot |
| `SERVER_IP` | Yes | `""` | Server public IP |
| `VLESS_PBK` | Yes | `""` | X25519 public key for Reality (primary inbound) |
| `VLESS_SID` | Yes | `""` | Short ID for Reality (primary inbound) |
| `ADMIN_IDS` | No | `319665243` | Comma-separated admin Telegram IDs |
| `DB_PATH` | No | `./data/vpn_seller.sqlite` | SQLite database path |
| `XRAY_CONFIG_PATH` | No | `/opt/vpn-core/conf/config.json` | Xray config location |
| `XRAY_SERVICE` | No | `vpn-core-xray` | systemd service name |
| `STARS_PRICE_30/90/180` | No | `160/430/795` | Telegram Stars prices |
| `PRICE_USDT_30/90/180` | No | `2.0/5.4/10.0` | USDT prices |
| `TRIAL_MINUTES` | No | `30` | Trial duration (minutes) |
| `TRIAL_MAX_PER_USER` | No | `1` | Max trials per user |
| `REFERRAL_BONUS_DAYS` | No | `7` | Referral bonus days |
| `LANG_DEFAULT` | No | `ru` | Default language |

Full list with defaults: `bot.py` L27–89.

### Xray Setup

1. Generate Reality key pair:
   ```bash
   /opt/vpn-core/bin/xray x25519
   ```
2. Copy `vpn-core/config.template.json` → `/opt/vpn-core/conf/config.json`
3. Fill in `privateKey`, `shortIds` for the primary inbound
4. Set `VLESS_PBK` (public key) and `VLESS_SID` in `.env`

### systemd Units

| Service | Unit File | Purpose |
|---|---|---|
| `vpn-core-xray` | `systemd/vpn-core-xray.service` | Xray server with sandboxing |
| Telegram bot | Not unitized currently (manual or custom) | Bot process |

To install the Xray unit:
```bash
sudo cp systemd/vpn-core-xray.service /etc/systemd/system/
sudo systemctl daemon-reexec
sudo systemctl enable --now vpn-core-xray
```

## Running the Bot

### Development / Manual
```bash
cd vpn-seller-bot
python3 bot.py
```

The bot uses a single-instance lock via `fcntl.flock()` on `./data/bot.lock` to prevent duplicate processes.

### Production (recommended)
Create a systemd unit or use `tmux`/`screen`. The bot handles graceful shutdown via `SIGTERM`/`SIGINT` signal handlers.

## Admin Tasks

### In-Bot Admin Commands

Available to Telegram IDs listed in `ADMIN_IDS` env var. Execute in chat with the bot.

| Command | Purpose | Source (~L1449) |
|---|---|---|
| `/admin stats` | User count, active subscriptions, revenue, system info | L1470–1498 |
| `/admin issue tg_id` | Show user's subscription + invoice history | L1500–1559 |
| `/admin revoke sub_id` | Deactivate a specific subscription | L1561–1595 |
| `/admin broadcast MESSAGE` | Send a message to all users (error-tolerant) | L1598–1612 |
| `/admin health` | Full health report (xray service, port, connections, traffic, load) | L1614–1647 |
| `/admin traffic` | Monthly traffic stats via vnStat | L1649–1666 |
| `/admin backup` | Create backup on demand | L1581 (via kb_admin) |
| `/admin restore` | List + restore from backups | L1581 (via kb_admin) |

### CLI Admin Tool (`admin_key.py`)

Useful when the bot is down or for creating admin keys.

```bash
# Grant 30-day access
python3 admin_key.py <telegram_user_id> 30

# Grant 90 days with note
python3 admin_key.py <telegram_user_id> 90 --note "admin access"

# Dry run (no DB or xray changes)
python3 admin_key.py <telegram_user_id> 30 --dry-run

# Custom link name
python3 admin_key.py <telegram_user_id> 30 --name "my-key"
```

Key difference from bot: `admin_key.py` does NOT deactivate other keys for the same user. It supports multi-key access.

### Promo Code Management

Promo codes are managed directly in SQLite:
```bash
# Insert a 20% discount code (5 uses max)
sqlite3 data/vpn_seller.sqlite "INSERT INTO promo_codes (code, kind, value, max_uses, expires_at, created_at) VALUES ('SUMMER20', 'percent', 20, 5, $(date -d '+30 days' +%s), $(date +%s))"

# Insert a $1 fixed discount
sqlite3 data/vpn_seller.sqlite "INSERT INTO promo_codes (code, kind, value, max_uses, expires_at, created_at) VALUES ('SAVE1', 'usdt', 1.0, 10, $(date -d '+30 days' +%s), $(date +%s))"

# Insert bonus days
sqlite3 data/vpn_seller.sqlite "INSERT INTO promo_codes (code, kind, value, max_uses, expires_at, created_at) VALUES ('BONUS7', 'days', 7, 100, $(date -d '+30 days' +%s), $(date +%s))"
```

Promo codes are UPPERCASED automatically on use. Users enter them via `/promo CODE` command in the bot.

## Monitoring

### vpn-watch Monitoring Script

**Location**: `vpn-core/vpn-watch.py`

**Usage**:
```bash
# One-shot check → writes JSON status file
python3 vpn-core/vpn-watch.py

# One-shot check → prints to stdout
python3 vpn-core/vpn-watch.py --live
```

**Recommended cron**: `*/5 * * * * /opt/vpn-core/vpn-watch.py`

**Output**: Writes to `/opt/vpn-core/conf/vpn-watch-status.json`:
```json
{
  "ts": 1700000000,
  "service": "active",
  "port_status": "open",
  "traffic_active": true,
  "rx_rate": 102400,
  "tx_rate": 51200,
  "elapsed_s": 300,
  "xray_errors": 0,
  "connections_total": 15,
  "connections_established": 12,
  "conntrack_restarted": false
}
```

**Auto-remediation**: If >500 total connections exist and <10% are ESTABLISHED, Xray is automatically restarted (conntrack overflow detector). This prevents resource exhaustion from dead sessions.

### Bot Health Commands

- `/health` — Public endpoint: returns "✅ ok" or "❌ service down". Admin sees full detail.
- `/test` — User-facing diagnostics: ping, port scanning, Xray status, subscription info, server load.

### Important Files to Monitor

| Path | What to Watch |
|---|---|
| `/opt/vpn-core/conf/vpn-watch-status.json` | Latest monitoring snapshot |
| `/opt/vpn-core/conf/vpn-watch.log` | Conntrack overflow restart log |
| `/var/log/xray/access.log` | Xray traffic and error log |
| `/opt/vpn-seller-bot/data/vpn_seller.sqlite` | Production database |

## Backup & Restore

### Automated Backups
- Frequency: Every 24h (controlled by `BACKUP_INTERVAL_SEC`, default 86400)
- Scope: DB + Xray config + WireGuard config → tar.gz
- Location: `BACKUP_DIR` (default `/opt/vpn-seller-bot/backups/`)
- Retention: `BACKUP_KEEP_DAYS` (default 7 days)

### Manual Backup
```
/admin backup → creates tar.gz
```

### Manual Restore
```
/admin restore → shows file list
/admin restore <filename> → restores
```

Restore validates path traversal: only files within `BACKUP_DIR` can be restored (source: `bot.py` L2470–2502).

## Security Measures

| Measure | Where | Detail |
|---|---|---|
| Xray sandboxing | systemd unit | `ProtectSystem=strict`, `ProtectHome=true`, `PrivateTmp=true` |
| SSH hardening | Server config | Port 29001 (not 22), fail2ban |
| Conntrack protection | vpn-watch.py | Auto-restarts Xray on dead session overflow |
| Config validation | bot.py + admin_key.py | `xray run -test` before applying; rollback on failure |
| Single instance lock | bot.py L2665–2675 | `fcntl.flock()` prevents duplicate bot processes |
| Provision serialization | bot.py L17, L1197 | `asyncio.Lock` prevents concurrent Xray/WG writes |
| DDoS protection | iptables | `hashlimit` on all ports (per ROADMAP.md) |

## Troubleshooting

### Xray won't start
1. Check config syntax: `/opt/vpn-core/bin/xray run -test -config /opt/vpn-core/conf/config.json`
2. Check systemd: `systemctl status vpn-core-xray`
3. Check logs: `journalctl -u vpn-core-xray --no-pager -n 50`

### Bot won't start
1. Check `.env` has `TELEGRAM_BOT_TOKEN`
2. Check for existing lock file: `ls -la data/bot.lock`
3. Check SQLite database: `python3 -c "import sqlite3; conn = sqlite3.connect('data/vpn_seller.sqlite'); print(conn.execute('SELECT count(*) FROM users').fetchone())"`

### Payments not being fulfilled
1. Check CryptoBot token in `.env`
2. Check `fulfilled_at` column: `sqlite3 data/vpn_seller.sqlite "SELECT invoice_id, status, fulfilled_at FROM invoices WHERE status='paid' ORDER BY paid_at DESC LIMIT 10"`
3. Check bot logs for `Provisioning` log lines

## Updating

- **Database migrations**: The bot handles schema evolution via `PRAGMA table_info()` + `ALTER TABLE ADD COLUMN` on startup. No Alembic/migration framework required.
- **Xray config template**: Update `config.template.json` in git, then manually update `/opt/vpn-core/conf/config.template.json` on the server. The bot uses this template for rebuilds.
- **Xray binary**: Upgrade separately via the Xray install script (not managed by this repo).

## Change Guidance

- **Adding a new environment variable**: Add to the `.env.example` (not in Git yet — create one), add to the parsing block at `bot.py` L27–89, add to `admin_key.py` ~L22–34 if needed there too.
- **Changing monitoring interval**: Update the cron entry on the server (not in code). The script is stateless between runs.
- **Adding a new cron check**: Add a new function in `vpn-watch.py`, add it to the `status` dict in `main()`, and add to `--live` output. The JSON output is read by the bot's `/admin health` path.
- **systemd unit changes**: Update `systemd/vpn-core-xray.service` in git and redeploy on the server. Be careful with sandboxing flags — Xray/Go has specific syscall requirements (see commit `680d137` which removed `SystemCallFilter` for compatibility).
