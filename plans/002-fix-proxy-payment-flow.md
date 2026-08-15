# Plan 002: Починить платёжный flow для MTProto-прокси

> **Executor instructions**: Следуй этому плану шаг за шагом. Запускай каждую команду верификации и подтверждай ожидаемый результат перед переходом дальше. Рабочая директория: `/opt/vpn-seller-bot`.

## Status

- **Priority**: P1
- **Effort**: S
- **Risk**: LOW
- **Depends on**: none
- **Category**: bug
- **Planned at**: 2026-06-11

## Why this matters

Колбэк `buy_proxy_l1` (bot.py:2097-2110) напрямую создаёт подписку `sub_type='proxy'` на 30 дней в БД — без создания инвойса, без крипто-платежа. Любой пользователь получает бесплатный MTProto-прокси простым нажатием кнопки. Потеря выручки $0.50 с каждого. Правильный flow (создание инвойса → проверка оплаты → provision) уже реализован для VLESS-тарифов (buy_30/90/180) — нужно просто применить его к прокси.

## Current state

- `bot.py:2097-2110` — текущий (сломанный) код:
```python
if data == "buy_proxy_l1":
    await clear_keyboard(bot, query.message.chat.id, query.message.message_id)
    now = int(time.time())
    new_uuid = "proxy_" + str(tg_id)
    with db() as conn:
        conn.execute(
            "INSERT INTO subscriptions (tg_id, uuid, active, expires_at, sub_type, created_at) VALUES (?,?,1,?,?,?)",
            (tg_id, new_uuid, now + 30*86400, 'proxy', now)
        )
        conn.commit()
    expires = time.strftime('%Y-%m-%d %H:%M', time.localtime(now + 30*86400))
    await bot.send_message(query.message.chat.id, t("proxy_access", lang).format(expires))
    return
```

- `bot.py:1738-1790` — образец правильного flow: `create_invoice_for_days()` создаёт инвойс через CryptoBot API, пишет в таблицу `invoices`, запускает `auto_check_invoice()`
- `bot.py:1109-1252` — `auto_check_invoice()` проверяет статус инвойса, при `paid` вызывает `provision_access()`

## Scope

**In scope:**
- `bot.py` — заменить строки 2097-2110
- Только этот колбэк

**Out of scope:**
- Изменение цен (оставить $0.50 / 30 дней)
- Любые другие колбэки
- Таблица `invoices` (уже существует, supports `meta` JSON)

## Steps

### Step 1: Заменить `buy_proxy_l1` на создание инвойса

Заменить блок `if data == "buy_proxy_l1":` (строки 2097-2110) на:

```python
if data == "buy_proxy_l1":
    await clear_keyboard(bot, query.message.chat.id, query.message.message_id)
    # Получить актуальный курс TON
    rate = await get_ton_rate()
    if not rate:
        await bot.send_message(query.message.chat.id, t("rate_error", lang))
        return
    # Создать инвойс через CryptoBot
    amount_ton = round(0.50 / rate, 4)  # $0.50 в TON
    payload = json.dumps({"type": "proxy", "days": 30, "tg_id": tg_id})
    invoice = await create_crypto_invoice(amount_ton, f"MTProto Proxy 30 дней", payload)
    if not invoice:
        await bot.send_message(query.message.chat.id, t("invoice_error", lang))
        return
    # Сохранить инвойс в БД
    invoice_id = invoice["result"]["invoice_id"]
    with db() as conn:
        conn.execute(
            "INSERT INTO invoices (tg_id, invoice_id, amount, amount_ton, currency, status, payload, created_at) VALUES (?,?,?,?,?,?,?,?)",
            (tg_id, invoice_id, 0.50, amount_ton, "TON", "pending", payload, int(time.time()))
        )
        conn.commit()
    # Запустить фоновую проверку
    await start_auto_check(tg_id, invoice_id)
    # Показать кнопку проверки
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=t("btn_check", lang), callback_data=f"check_{invoice_id}")],
        [InlineKeyboardButton(text=t("btn_support", lang), callback_data="support")],
    ])
    await bot.send_message(
        query.message.chat.id,
        t("invoice_msg", lang).format(amount=amount_ton, currency="TON", usd="0.50"),
        reply_markup=kb
    )
    return
```

**Verify**: проверить что код ссылается на существующие функции — `get_ton_rate()` (line 534), `create_crypto_invoice()` (line 496), `start_auto_check()` (должна существовать; если нет — использовать `auto_check_invoice` напрямую через `asyncio.create_task`)

### Step 2: Убедиться что `provision_access()` обрабатывает `sub_type='proxy'`

`provision_access()` (bot.py:1077-1177) должна различать обычный VLESS и прокси. Проверить что при `sub_type='proxy'` она вызывает прокси-провижининг (аналог строк 2100-2106), а не пытается перестроить Xray-конфиг.

Если `provision_access()` не обрабатывает `proxy` — добавить в неё ветку:

```python
if sub_type == 'proxy':
    new_uuid = "proxy_" + str(tg_id)
    with db() as conn:
        conn.execute(
            "INSERT INTO subscriptions (tg_id, uuid, active, expires_at, sub_type, created_at) VALUES (?,?,1,?,?,?)",
            (tg_id, new_uuid, now + days*86400, 'proxy', now)
        )
        conn.commit()
    return
```

**Verify**: `grep -n "sub_type.*proxy\|proxy.*sub_type" bot.py` — должен найти обработку в `provision_access`.

### Step 3: Перезапустить бота и проверить

```bash
sudo systemctl restart vpn-seller-bot && sleep 2 && sudo systemctl is-active vpn-seller-bot
```

**Verify**: `active`. Затем в Telegram: нажать кнопку прокси → должен появиться инвойс (не мгновенная выдача).

## Done criteria

- [ ] Нажатие «MTProto Proxy» создаёт CryptoBot-инвойс, а не мгновенную подписку
- [ ] Инвойс сохраняется в таблицу `invoices`
- [ ] При оплате инвойса создаётся подписка `sub_type='proxy'` на 30 дней
- [ ] `sudo journalctl -u vpn-seller-bot --no-pager -n 20` — нет ошибок

## STOP conditions

- Если `create_crypto_invoice()` или `get_ton_rate()` не существуют (переименованы/удалены) → STOP, найти актуальные имена функций
- Если `auto_check_invoice` не распознаёт `type: "proxy"` в payload → STOP, добавить обработку
- Если `provision_access` делает Xray-рестарт для proxy-подписки → STOP, это ломает VPN-клиентов

## Maintenance notes

- Цена прокси ($0.50) захардкожена в коде — как и VLESS-цены (PRICE_USDT_30). При изменении цены менять в одном месте.
- Payload `{"type": "proxy", "days": 30}` должен разбираться в `auto_check_invoice()` — убедиться что `json.loads(meta)` обрабатывает этот случай.
