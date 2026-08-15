# Plan 003: Добавить миграцию sub_type в init_db()

> **Executor instructions**: Следуй плану шаг за шагом. Рабочая директория: `/opt/vpn-seller-bot`.

## Status
- **Priority**: P1 | **Effort**: S | **Risk**: LOW | **Category**: bug | **Planned at**: 2026-06-11

## Why this matters

Колонка `sub_type` используется в `latest_sub_type()` (line 610), `provision_access()` и INSERT в `buy_proxy_l1` (line 2104). Но `CREATE TABLE subscriptions` в `init_db()` (lines 419-433) не содержит эту колонку и нет ALTER TABLE для неё. На чистой БД (новый сервер, удаление sqlite) бот упадёт с `sqlite3.OperationalError: no such column: sub_type`.

## Current state

- `bot.py:419-433` — CREATE TABLE subscriptions: колонки `tg_id, uuid, active, expires_at, created_at, wg_ip, privkey, pubkey`. `sub_type` отсутствует.
- `bot.py:441-449` — существующий паттерн миграции для `wg_ip/privkey/pubkey`: проверка через `PRAGMA table_info`, ALTER TABLE. Надо добавить такой же для `sub_type`.

## Steps

### Step 1: Добавить миграцию в init_db()

В `bot.py:449` (после блока миграции для wg_ip/privkey/pubkey) добавить:

```python
# Миграция: sub_type (proxy support)
cols = {row[1] for row in conn.execute("PRAGMA table_info(subscriptions)").fetchall()}
if "sub_type" not in cols:
    conn.execute("ALTER TABLE subscriptions ADD COLUMN sub_type TEXT")
    conn.commit()
    log.info("Migration: added sub_type column to subscriptions")
```

**Verify**: `python3 -c "import sqlite3; c=sqlite3.connect(':memory:'); c.execute('CREATE TABLE subscriptions (tg_id INT)'); c.execute('ALTER TABLE subscriptions ADD COLUMN sub_type TEXT'); print('OK')"` → OK.

### Step 2: Перезапустить бота

```bash
sudo systemctl restart vpn-seller-bot && sleep 2 && sudo journalctl -u vpn-seller-bot --no-pager -n 5 | grep -i "migration\|error"
```

**Verify**: нет ошибок. При первом запуске должна появиться строка "Migration: added sub_type column".

## Done criteria
- [ ] `python3 -c "import sqlite3; c=sqlite3.connect('$DB_PATH'); print([r[1] for r in c.execute('PRAGMA table_info(subscriptions)')])"` — содержит `sub_type`
- [ ] Бот работает, нет ошибок в логах

## STOP conditions
- Если миграция падает с `duplicate column name` → колонка уже существует, пропустить (IF NOT EXISTS не поддерживается в ALTER TABLE SQLite, используем проверку)
