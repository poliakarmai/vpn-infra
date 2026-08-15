# Plan 004: SQLite — WAL-режим и индексы

> **Executor instructions**: Следуй плану шаг за шагом. Рабочая директория: `/opt/vpn-seller-bot`.

## Status
- **Priority**: P1 | **Effort**: S | **Risk**: LOW | **Category**: perf | **Planned at**: 2026-06-11

## Why this matters

`db()` создаёт новый коннект при каждом вызове (41 место), использует rollback journal (читатели блокируются писателями), и НИ ОДНОГО индекса. При конкурентных хендлерах бота это даёт линейный рост latency и O(N) сканы на каждом `WHERE tg_id=?`.

## Steps

### Step 1: WAL-режим + synchronous=NORMAL

В функции `db()` (bot.py:362-366), после `conn = sqlite3.connect(DB_PATH)`:

```python
conn.row_factory = sqlite3.Row
conn.execute("PRAGMA journal_mode=WAL")
conn.execute("PRAGMA synchronous=NORMAL")
conn.execute("PRAGMA cache_size=-8000")  # 8 MB cache
conn.execute("PRAGMA busy_timeout=5000")
```

**Verify**: `python3 -c "import sqlite3; c=sqlite3.connect('/opt/vpn-seller-bot/data/vpn_seller.sqlite'); print(c.execute('PRAGMA journal_mode').fetchone()[0])"` → `wal`.

### Step 2: Добавить индексы

В `init_db()` после CREATE TABLE блока добавить:

```python
conn.execute("CREATE INDEX IF NOT EXISTS idx_subs_active_tg ON subscriptions(tg_id, active)")
conn.execute("CREATE INDEX IF NOT EXISTS idx_subs_expires ON subscriptions(expires_at) WHERE active=1")
conn.execute("CREATE INDEX IF NOT EXISTS idx_inv_tg_status ON invoices(tg_id, status)")
conn.execute("CREATE INDEX IF NOT EXISTS idx_inv_invoice_id ON invoices(invoice_id)")
conn.execute("CREATE INDEX IF NOT EXISTS idx_users_referrer ON users(referrer_tg_id)")
conn.commit()
```

**Verify**: `python3 -c "import sqlite3; c=sqlite3.connect('/opt/vpn-seller-bot/data/vpn_seller.sqlite'); print(len(c.execute(\"SELECT name FROM sqlite_master WHERE type='index'\").fetchall()))"` → ≥5.

### Step 3: Рестарт бота

```bash
sudo systemctl restart vpn-seller-bot && sleep 2 && sudo systemctl is-active vpn-seller-bot
```

## Done criteria
- [ ] `PRAGMA journal_mode` returns `wal`
- [ ] Минимум 5 индексов в `sqlite_master`
- [ ] Бот работает, `/admin stats` отвечает без задержек
