# Domain Concepts

## Subscription Lifecycle

A subscription represents a user's right to use the VPN service for a period of time.

```
┌─────────┐    purchase     ┌──────────────┐    expiry    ┌──────────┐
│  Trial  │ ─────────────→  │   Active     │ ──────────→  │ Expired  │
│ (30min) │                 │  Subscription │              │ (active  │
└─────────┘                 │  (paid)      │              │  = 0)    │
                            └──────────────┘              └──────────┘
                                   │ ↑
                                   │ │ extend (keeps UUID)
                                   ▼ │
                            ┌──────────────┐
                            │  Extended    │
                            │  (expires_at │
                            │  += days)    │
                            └──────────────┘
```

**Key rules** (source: `bot.py` L672–700):
- A trial subscription does NOT extend an existing paid subscription.
- Extending an active subscription keeps the same UUID (client key remains the same).
- If the subscription has already expired, a new UUID is generated.
- The `reconcile_subscriptions()` function (~L832) runs on startup and periodically to mark expired subscriptions as `active=0`.

### Subscription Types (`sub_type` column)

| Value | Protocol | Config Source |
|---|---|---|
| `NULL` | VLESS+REALITY (primary) | Xray config, port 4443 |
| `"proxy"` | MTProto Proxy | MTProto port 8443 |
| `"wireguard"` | WireGuard / AmneziaWG | wg0.conf, port 51820 |

## Pricing

Current price structure (source: `bot.py` L30–33):

| Duration | USD Price | Telegram Stars | Discount |
|---|---|---|---|
| 30 days | $2.00 | 160 Stars | — |
| 90 days | $5.40 | 430 Stars | −10% |
| 180 days | $10.00 | 795 Stars | −20% |

Note: Stars prices are in Telegram's proprietary star currency, not directly tied to USD.

## Payment Methods

### 1. Telegram Stars (Instant)
- **Flow**: Bot sends `sendInvoice()` with `currency="XTR"` via Telegram API → user sees native payment sheet → pre_checkout_query handler auto-accepts → successful_payment handler provisions immediately (source: `bot.py` L2706–2747)
- **Pros**: No external API polling needed; instant fulfillment
- **Integration point**: `on_pre_checkout_query()`, `on_successful_payment()`

### 2. CryptoBot (TON / USDT)
- **Flow**: Bot creates invoice via `https://pay.crypt.bot/api/createInvoice` → user clicks link → pays in CryptoBot chat → bot polls every 12s for up to 180s (source: `bot.py` L1840–1882, L1296–1376)
- **Automated check**: Background `auto_check_invoice()` initiates when user clicks "Check Payment" or automatically on invoice creation
- **TON rate**: Fetched from CoinGecko and Binance, cached in SQLite `rate_cache` table with configurable TTL (default 300s)
- **Idempotency**: `fulfilled_at` column prevents double-provisioning

## Promo Codes

Every user interaction with promo codes is tracked. Source: `bot.py` L729–814.

### Types

| `kind` | Effect | Example |
|---|---|---|
| `percent` | Discounts price by percentage | `"percent", 20` → 20% off |
| `usdt` | Fixed discount in USDT | `"usdt", 0.5` → $0.50 off |
| `days` | Bonus days added to subscription | `"days", 7` → +7 free days |

### Business Rules
- `max_uses` limits total redemptions across all users
- `UNIQUE(tg_id, code)` constraint prevents a user from redeeming the same code twice
- Redemption is atomic: the SQL `UPDATE ... WHERE used_count < max_uses` + `INSERT` are in a single transaction with `IntegrityError` rollback
- Expired promo codes are not usable
- The TOCTOU race condition was fixed with atomic SQL (audit fix, commit `b9c3c61`)

## Referral Program

- Each user is assigned a `referrer_tg_id` when they start via a referral link (`?start=ref_<tg_id>`)
- On first paid subscription by the referred user, the referrer gets `REFERRAL_BONUS_DAYS` (default 7) added to their subscription
- Self-referral is blocked (source: `bot.py` L1213–1215)
- Referral link format: `https://t.me/Poliakarbot?start=ref_319665243`

## Database Schema

SQLite database at path specified by `DB_PATH` env var (default `./data/vpn_seller.sqlite`). 6 tables, created in `init_db()` at `bot.py` L412–547.

### `users`
| Column | Type | Purpose |
|---|---|---|
| `tg_id` | INTEGER PK | Telegram user ID |
| `created_at` | INTEGER | Registration timestamp |
| `main_chat_id` / `main_message_id` | INTEGER | For updating the main UI screen in-place |
| `trial_used` | INTEGER DEFAULT 0 | Trial usage count |
| `referrer_tg_id` | INTEGER | Referrer's tg_id |
| `lang` | TEXT | Language preference ("ru" or "en") |

### `subscriptions`
| Column | Type | Purpose |
|---|---|---|
| `id` | INTEGER PK AUTO | Auto-increment |
| `tg_id` | INTEGER | User |
| `uuid` | TEXT | VLESS client UUID |
| `created_at` / `expires_at` | INTEGER | Timestamps |
| `active` | INTEGER | 1=active, 0=expired/revoked |
| `wg_ip` / `wg_privkey` / `wg_pubkey` | TEXT | WireGuard keys (only for WG subscriptions) |
| `sub_type` | TEXT | NULL=VLESS, "proxy", "wireguard" |

### `invoices`
| Column | Type | Purpose |
|---|---|---|
| `id` | INTEGER PK AUTO | Auto-increment |
| `tg_id` | INTEGER | User |
| `invoice_id` | TEXT UNIQUE | CryptoBot invoice ID |
| `asset` | TEXT | "TON", "USDT" |
| `amount` | REAL | Amount in asset |
| `status` | TEXT | "active", "paid", "expired" |
| `created_at` / `paid_at` / `fulfilled_at` | INTEGER | Timestamps |
| `meta` | TEXT | JSON blob: `{days, promo, bonus_days, type}` |

### `promo_codes`
| Column | Type | Purpose |
|---|---|---|
| `code` | TEXT PK | Uppercased promo code |
| `kind` | TEXT | "percent", "usdt", "days" |
| `value` | REAL | Discount/bonus amount |
| `max_uses` | INTEGER | Usage limit |
| `used_count` | INTEGER DEFAULT 0 | Current usage |
| `expires_at` / `created_at` | INTEGER | Timestamps |

### `promo_redemptions`
Tracks which user redeemed which code. `UNIQUE(tg_id, code)` prevents double-redeem.

### `rate_cache`
Caches TON/USD exchange rate from CoinGecko/Binance.

### `expiry_notifications`
Tracks sent notifications per subscription + hours_before window. `UNIQUE(subscription_id, hours_before)` ensures idempotent notifications.

## i18n / Internationalization

Source: `bot.py` L91–331.

- All user-facing strings stored in a `T` dictionary with `"ru"` and `"en"` translations
- `t(key, lang, *args)` helper looks up the key, prefers user's language, falls back `en` → `ru` → raw key
- Language stored per-user in `users.lang`, default from `LANG_DEFAULT` env var (`"ru"`)
- Language can be changed via `/lang` command or inline button

## Change Guidance

- **New subscription type**: Add a `sub_type` value, create provisioning handlers (~L1187), add to `latest_sub_type()` (~L664), add config generation if needed (new Xray/WG/protocol logic).
- **New payment method**: Create invoice table row with `invoice_id`, implement check flow (polling or webhook), set `fulfilled_at` at the end. Follow CryptoBot pattern as reference.
- **New promo code kind**: Add to `promo_apply_price()` (~L799), update validation in `promo_can_redeem()` (~L739).
- **Changing TON rate source**: Update `_fetch_ton_rate_from_source()` (~L566) and source list at L345–348. The 4-layer fallback (memory → DB → API → stale) handles failures gracefully.
- **Adding/removing DB column**: The existing migration pattern uses `PRAGMA table_info()` + `ALTER TABLE ADD COLUMN` (see bot.py L427–488 for examples). Follow this pattern rather than adding a migration framework.
