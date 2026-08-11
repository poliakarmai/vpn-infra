# Architecture

## System Overview

The VPN infrastructure consists of four main components that work together to provide VPN key sales, provisioning, and monitoring.

```
┌─────────────────────────────────────────────────────────────────┐
│                        Internet                                  │
└─────┬────────────────────┬─────────────────┬─────────────────────┘
      │                    │                 │
      ▼                    ▼                 ▼
┌──────────┐     ┌──────────────┐   ┌──────────────┐
│ Telegram │     │   CryptoBot  │   │  CoinGecko   │
│  Users   │     │  (payments)  │   │  (TON rate)  │
└────┬─────┘     └──────┬───────┘   └──────┬───────┘
     │                  │                  │
     ▼                  ▼                  ▼
┌──────────────────────────────────────────────────┐
│              Telegram Bot (bot.py)                │
│                                                   │
│  ┌─────────┐  ┌──────────┐  ┌─────────────────┐  │
│  │aiogram  │  │CryptoBot │  │  Background      │  │
│  │Handlers │  │Payment   │  │  Scheduler       │  │
│  │         │  │Polling   │  │  (expiry, backup, │  │
│  │cmd_*    │  │          │  │   reconcile)      │  │
│  │on_cb*   │  │auto_check│  │                   │  │
│  └────┬────┘  └──────────┘  └────────┬──────────┘  │
│       │                              │              │
│       ▼                              ▼              │
│  ┌──────────────────────────────────────────────┐   │
│  │  Provisioning Engine                         │   │
│  │  - Subscription CRUD                         │   │
│  │  - Xray config generation + validation       │   │
│  │  - WireGuard peer management                 │   │
│  └──────────────────────┬───────────────────────┘   │
└─────────────────────────┼───────────────────────────┘
                          │
          ┌───────────────┼───────────────┐
          ▼               ▼               ▼
   ┌────────────┐  ┌────────────┐  ┌────────────┐
   │   Xray     │  │ WireGuard  │  │ MTProto    │
   │ (VLESS+    │  │ (UDP/TCP)  │  │ Proxy      │
   │  REALITY)  │  │            │  │            │
   └────────────┘  └────────────┘  └────────────┘
          │
          ▼
   ┌────────────┐
   │ vpn-watch  │  Monitoring (cron/systemd)
   └────────────┘
```

## Component Details

### 1. Telegram Bot (`vpn-seller-bot/bot.py`)

The central orchestration point. Built with **aiogram 3.4+**.

**Handlers** (~L1449–2330):
- `/start` — User registration, referral link parsing
- `/admin` — Stats, issue management, broadcast, health, traffic, backup, restore
- `/promo CODE` — Promo code redemption
- `/health` — Public health check endpoint
- `/test` — User-facing diagnostics (ping, ports, xray status)
- Callback handlers for all inline button interactions

**Payment Processing** (~L1187–1376):
- Telegram Stars via `send_invoice()` API — instant fulfillment on `pre_checkout_query` + `successful_payment`
- CryptoBot (TON/USDT) — invoice creation via `https://pay.crypt.bot/api/`, background polling loop every 12s

**Background Scheduler** (~L2606–2657):
- Periodic reconciliation: expire subscriptions, rebuild Xray config
- Auto-expire stale invoices (>24h)
- Expiry notifications (72h and 24h before expiry)
- Daily SQLite database backup

**Provisioning** (~L844–938, ~L942–1032):
- Templates `config.template.json` → inserts active client UUIDs → runs `xray run -test` → systemctl reload
- Atomic write with `.bak` rollback on validation failure
- WireGuard peer addition/removal via `wg set` and config file manipulation

### 2. CLI Admin Tool (`vpn-seller-bot/admin_key.py`)

A standalone script for granting VPN keys without the bot. Useful for:
- Creating admin/backup keys
- Issuing keys when the bot is down
- Offline provisioning

Key difference from bot flow: **does NOT deactivate other active keys** (supports multi-key for the same user). Shares the same SQLite database, Xray config path, and reload mechanism as the bot.

### 3. Xray Server (`vpn-core/config.template.json` + systemd unit)

Two VLESS+REALITY inbounds for censorship resistance:

| Inbound Tag | Port | Camouflage SNI | Purpose |
|---|---|---|---|
| `vless-reality-seller` | 4443 | `www.cloudflare.com` | Primary — used by bot for all subscriptions |
| `vless-reality-backup` | 8445 | `www.apple.com` | Level 2 anti-censorship backup — configured manually |

Each inbound serves a dynamic `clients[]` list written by the provisioning engine. The systemd unit (`systemd/vpn-core-xray.service`) applies security sandboxing:
- `NoNewPrivileges=true`
- `ProtectSystem=strict`
- `ProtectHome=true`
- `PrivateTmp=true`

### 4. Monitoring Script (`vpn-core/vpn-watch.py`)

Runs as a cron job (every 5 min) or standalone. Checks:

| Check | Method | Auto-remediation |
|---|---|---|
| Xray service status | `systemctl is-active` | No |
| Port 4443 accessibility | `ss -tln` | No |
| Traffic rate (RX/TX) | `/proc/net/dev` for `ens3` | No |
| Xray error count | Grep access.log for rejected/error/failed/timeout | No |
| Conntrack overflow | `ss -tn` session count; if >500 and <10% established, auto-restart | Restarts Xray via systemctl |

Writes JSON status to `/opt/vpn-core/conf/vpn-watch-status.json` read by the bot's `/test` and `/admin health` commands.

## Data Flow: User Purchases a VPN Key

```
1. User opens bot → sees main screen (pricing, status)
2. Clicks "Buy 30 days" → bot shows payment method selection
3. User selects TON → bot creates CryptoBot invoice via API
4. Bot sends invoice link → user pays in CryptoBot chat
5. Background auto_check loop polls every 12s for 180s max
6. On payment detected:
   a. Generates uuid.uuid4() for client
   b. Creates/extends subscription record in SQLite
   c. Applies referral bonus if applicable
   d. Calls rebuild_and_reload_xray() — atomic write + validate + restart
   e. Sends VLESS link + QR code to user
7. If Stars payment: handled via Telegram pre_checkout_query → successful_payment callback
```

## Key Configuration Files on Server

| Path | Contents | Managed By |
|---|---|---|
| `/opt/vpn-core/conf/config.json` | Live Xray config with active clients[] | Bot provisioning |
| `/opt/vpn-core/conf/config.template.json` | Template with placeholders | Git (manually updated) |
| `/opt/vpn-core/conf/vpn-watch-status.json` | Latest monitoring snapshot | vpn-watch.py |
| `/opt/vpn-core/conf/vpn-watch-prev.json` | Previous traffic sample for delta calculation | vpn-watch.py |
| `/opt/vpn-seller-bot/data/vpn_seller.sqlite` | SQLite database (users, subs, invoices, promos) | Bot |
| `/etc/wireguard/wg0.conf` | WireGuard config | Bot (wg commands) |

## Source Reference

| Component | File | Key Lines |
|---|---|---|
| Bot entry & startup | `/vpn-seller-bot/bot.py` | L2660–2779 |
| DB schema & migration | same | L412–547 |
| Xray config management | same | L844–938 |
| WireGuard management | same | L942–1032 |
| Provisioning logic | same | L1187–1258 |
| Payment processing | same | L1261–1376 |
| Admin commands | same | L1449–1672 |
| Background scheduler | same | L2606–2657 |
| i18n dictionary | same | L91–302 |
| CLI admin tool | `/vpn-seller-bot/admin_key.py` | Full file (197 lines) |
| Monitoring script | `/vpn-core/vpn-watch.py` | Full file (200 lines) |
| Xray config template | `/vpn-core/config.template.json` | Full file (84 lines) |
| systemd unit | `/systemd/vpn-core-xray.service` | Full file |
| Roadmap | `/vpn-seller-bot/ROADMAP.md` | Full |

## Change Guidance

When modifying architecture-critical code:

- **Changing Xray reload method**: Update `XRAY_RELOAD_METHOD` env var usage in `bot.py` and `admin_key.py`. Both must agree.
- **Adding a subscription type**: Add to `sub_type` column usage in `bot.py` DB queries (~L664–669), provisioning (~L1187), and `create_or_extend_sub()` (~L672). Add handlers for new type.
- **Changing provisioning serialization**: The `PROVISION_LOCK` (`asyncio.Lock` at L17) serializes all xray/WG changes — ensure any new provisioning path also acquires it.
- **New payment provider**: Follow the CryptoBot pattern: create invoice, store in `invoices` table with `invoice_id`, poll/check with `auto_check_invoice()`, mark `fulfilled_at` to prevent double-granting.
