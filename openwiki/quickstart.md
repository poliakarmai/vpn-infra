# VPN Infrastructure — Quickstart

Welcome to the **VPN Infrastructure** documentation. This repository operates a production VLESS+REALITY VPN server with a Telegram bot for automated key sales, payment processing, and subscription management.

## Repository Overview

A self-hosted VPN service that sells subscriptions via Telegram. The system uses **Xray** with the **VLESS+REALITY** protocol for censorship-resistant transport, and supports **WireGuard/AmneziaWG** and **MTProto Proxy** as alternative protocols. Payments flow through **CryptoBot (TON/USDT)** and **Telegram Stars**.

| Aspect | Detail |
|---|---|
| **Protocol** | VLESS+REALITY (primary port 4443, backup port 8445) |
| **Additional protocols** | WireGuard (51820/UDP), MTProto Proxy (8443), AmneziaWG |
| **Payment** | Telegram Stars, CryptoBot (TON, USDT) |
| **Bot framework** | aiogram 3.4+ |
| **Database** | SQLite (WAL mode) |
| **Auth** | UUID-based client keys, no passwords |
| **Users** | ~10 active (production) |

## Repository Structure

```
vpn-infra/
├── vpn-core/                    # Xray server + monitoring
│   ├── config.template.json     # Xray config template (placeholders)
│   └── vpn-watch.py             # Monitoring: service, port, traffic, conntrack
├── vpn-seller-bot/              # Telegram bot for selling VPN keys
│   ├── bot.py                   # Main bot (~2800 lines) — all handlers, provisioning, payments
│   ├── admin_key.py             # CLI admin tool: grant keys without the bot
│   ├── requirements.txt         # Python dependencies
│   └── ROADMAP.md               # Development roadmap (multi-level plan)
├── systemd/
│   └── vpn-core-xray.service    # systemd unit for Xray with sandboxing
├── AGENTS.md                    # AI agent navigation (informal spec + invariants)
├── CLAUDE.md                    # Agent instruction pointer
├── README.md                    # Project overview (Russian)
└── LICENSE                      # MIT
```

## Key Files

| File | Purpose | Start Reading |
|---|---|---|
| `vpn-seller-bot/bot.py` | All Telegram bot logic: commands, callbacks, payments, provisioning, monitoring, backups | ~L1449 (handlers), ~L2660 (main entry) |
| `vpn-seller-bot/admin_key.py` | Standalone CLI for admin key grants (no bot needed) | Full file (197 lines) |
| `vpn-core/vpn-watch.py` | Server monitoring: service health, port status, traffic rates, conntrack overflow detection | Full file (200 lines) |
| `vpn-core/config.template.json` | Xray config template with two VLESS+REALITY inbounds | Full file (84 lines) |
| `systemd/vpn-core-xray.service` | Secure systemd unit for Xray process | Full file |

## Documentation Pages

| Page | What It Covers |
|---|---|
| [Architecture](architecture.md) | System components, data flow, protocol details |
| [Domain Concepts](domain.md) | Subscriptions, payments, referrals, promo codes, database schema |
| [Operations Guide](operations.md) | Deployment, environment variables, admin tasks, monitoring, backups |

## Quick Start (Development)

```bash
# 1. Set up the bot
cd vpn-seller-bot
pip install -r requirements.txt

# 2. Configure environment
cp .env.example .env
# Edit .env — set TELEGRAM_BOT_TOKEN, CRYPTOBOT_TOKEN, SERVER_IP, VLESS_PBK, etc.

# 3. Run the bot
python3 bot.py
```

## Quick Start (Production Xray)

```bash
# Install Xray (see xray official guide)
# Copy config template → /opt/vpn-core/conf/config.json and fill in REALITY keys
# Place systemd unit and enable:
sudo cp systemd/vpn-core-xray.service /etc/systemd/system/
sudo systemctl daemon-reexec
sudo systemctl enable --now vpn-core-xray

# Verify
systemctl status vpn-core-xray
python3 vpn-core/vpn-watch.py --live
```

## Important Invariants

These invariants (from [AGENTS.md](../AGENTS.md)) must never be violated:

1. **VLESS+REALITY, not XTLS.** REALITY outperforms XTLS at DPI circumvention.
2. **Keys = UUID + short_id.** No passwords. Every client gets a UUID generated via `uuid.uuid4()`.
3. **Payments through Telegram Stars.** TON is the underlying asset, accessed via CryptoBot (fragment.com).
4. **Xray config not in Git.** Only `config.template.json` (with placeholders) lives in the repo. The real config is at `/opt/vpn-core/conf/config.json`.

## Security Notes

- Never commit `.env`, `config.json`, or private keys to the repository.
- The systemd unit applies sandboxing: `ProtectSystem=strict`, `ProtectHome=true`, `PrivateTmp=true`.
- Admin commands require the sender's `tg_id` to be in `ADMIN_IDS` env var.
- SQLite uses WAL mode for concurrent read safety.
- Provisioning is serialized with an `asyncio.Lock` to prevent race conditions on Xray/WireGuard config writes.
