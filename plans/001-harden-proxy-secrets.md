# Plan 001: Убрать хардкод прокси-секретов из исходного кода

> **Executor instructions**: Следуй этому плану шаг за шагом. Запускай каждую команду верификации и подтверждай ожидаемый результат перед переходом дальше. Если что-либо из секции «STOP conditions» происходит — остановись и доложи. Рабочая директория: `/opt/vpn-seller-bot`.

## Status

- **Priority**: P1
- **Effort**: S
- **Risk**: LOW
- **Depends on**: none
- **Category**: security
- **Planned at**: 2026-06-11 (no git — production snapshot)

## Why this matters

В `bot.py:173` захардкожены IP-адрес сервера (`2.27.48.142`), порт (`8443`) и секрет MTProto-прокси (`a905c98d3a3dc6d88e82428632aa98ab`) прямо в i18n-словаре. Эти значения видны всем у кого есть доступ к коду (бэкапы, логи, будущий git-репозиторий). При компрометации секрета его нужно менять на сервере И в коде. После выноса в `.env` секрет можно будет ротировать без изменения кода.

## Current state

- `bot.py:173` — строка `proxy_access` в словаре `T` содержит хардкод:
  ```
  Сервер: **2.27.48.142**
  Порт: **8443**
  Секрет: `a905c98d3a3dc6d88e82428632aa98ab`
  ```
- `bot.py:50-55` — существующий паттерн чтения из `.env`: `SERVER_IP = os.environ.get("SERVER_IP", "").strip()`
- Конвенция: все чувствительные параметры уже вынесены в `.env` (SERVER_IP, VLESS_PORT, VLESS_PBK, etc.) — прокси-параметры остались исключением.

## Scope

**In scope:**
- `bot.py` — строки 26-78 (добавить чтение PROXY_* переменных), строка 173 (заменить хардкод на `.format()`)
- `.env` — добавить PROXY_SERVER, PROXY_PORT, PROXY_SECRET (если ещё не добавлены)

**Out of scope:**
- Сама ротация секрета на прокси-сервере (отдельная операция после деплоя)
- Любые другие изменения в bot.py

## Steps

### Step 1: Добавить переменные окружения

В блоке конфигурации `bot.py:50-78` (после строки 55 `VLESS_SID = ...`) добавить:

```python
PROXY_SERVER = os.environ.get("PROXY_SERVER", SERVER_IP).strip()
PROXY_PORT = int(os.environ.get("PROXY_PORT", "8443"))
PROXY_SECRET = os.environ.get("PROXY_SECRET", "").strip()
```

**Verify**: `python3 -c "import os; os.environ['PROXY_SERVER']='test'; exec(open('bot.py').read().split('BOT_TOKEN')[0] + 'BOT_TOKEN=\"\"\\n' + open('bot.py').read().split('BOT_TOKEN')[1].split('T = {')[0]); print(PROXY_SERVER)"` — должен вывести `test`.

### Step 2: Заменить хардкод в i18n-строке

Заменить `bot.py:173` — строку `proxy_access` (и RU и EN варианты) — на использование `.format()`:

```python
"proxy_access": {
    "ru": "🔑 Твой MTProto прокси:\n\nСервер: **{server}**\nПорт: **{port}**\nСекрет: `{secret}`\n\n🔗 Ссылка: tg://proxy?server={server}&port={port}&secret={secret}\n\n🌀 **Keenetic роутер:**\nИнтернет → Прокси-сервер → Добавить\nТип: MTProto\nСервер: {server}\nПорт: {port}\nСекрет: {secret}\n\nАктивен до: {{}}\n\n⚠️ Если перестал — порт 443.",
    "en": "🔑 Your MTProto proxy:\n\nServer: **{server}**\nPort: **{port}**\nSecret: `{secret}`\n\n🔗 Link: tg://proxy?server={server}&port={port}&secret={secret}\n\n🌀 **Keenetic router:**\nInternet → Proxy server → Add\nType: MTProto\nServer: {server}\nPort: {port}\nSecret: {secret}\n\nActive until: {{}}\n\n⚠️ If down — port 443."
},
```

Обрати внимание: `{expires}` заменён на `{{}}` (экранирование для `.format()`), чтобы внешний код `t("proxy_access", lang).format(expires)` сначала применил `t()`, а потом `.format(expires)`.

### Step 3: Обновить место вызова

В `bot.py:2109` заменить:
```python
await bot.send_message(query.message.chat.id, t("proxy_access", lang).format(expires))
```
на:
```python
await bot.send_message(query.message.chat.id, t("proxy_access", lang).format(
    server=PROXY_SERVER, port=PROXY_PORT, secret=PROXY_SECRET
).format(expires))
```

ИЛИ лучше — изменить подход: пусть `t("proxy_access", lang)` возвращает строку с плейсхолдерами `{server}`, `{port}`, `{secret}`, `{expires}`, а вызывающий делает ОДИН `.format()`:

```python
await bot.send_message(query.message.chat.id, t("proxy_access", lang).format(
    server=PROXY_SERVER, port=PROXY_PORT, secret=PROXY_SECRET, expires=expires
))
```

Для этого в строке `proxy_access` заменить `{{}}` на `{expires}`.

**Verify**: `grep -n "2.27.48.142\|a905c98d3a3dc6d88e82428632aa98ab" bot.py` — должен вернуть 0 совпадений.

### Step 4: Добавить переменные в .env

В `/opt/vpn-seller-bot/.env` добавить:

```bash
PROXY_SERVER=2.27.48.142
PROXY_PORT=8443
PROXY_SECRET=a905c98d3a3dc6d88e82428632aa98ab
```

**Verify**: `grep -E "^PROXY_(SERVER|PORT|SECRET)=" .env | wc -l` → 3.

### Step 5: Перезапустить бота

```bash
sudo systemctl restart vpn-seller-bot && sleep 2 && sudo systemctl is-active vpn-seller-bot
```

**Verify**: `active`.

## Done criteria

- [ ] `grep -n "2.27.48.142\|a905c98d3a3dc6d88e82428632aa98ab" bot.py` returns 0 matches
- [ ] `grep -c "^PROXY_" .env` returns 3
- [ ] `sudo systemctl is-active vpn-seller-bot` returns `active`
- [ ] Бот отвечает на `/start` (проверить в Telegram)
- [ ] **После деплоя: ротировать секрет на MTProto-сервере и обновить PROXY_SECRET в .env**

## STOP conditions

- Если after restart бот падает с ошибкой импорта → проверить синтаксис f-строк в `proxy_access`
- Если `.format()` вызывает `KeyError` → проверить что все плейсхолдеры (`server`, `port`, `secret`, `expires`) совпадают в строке и в вызове `.format()`

## Maintenance notes

- При изменении IP сервера — обновить `PROXY_SERVER` в `.env`, рестарт бота не требуется (читается при старте)
- При ротации секрета — обновить `PROXY_SECRET` в `.env` И на самом прокси-сервере, затем рестарт бота
- Код больше не содержит секретов — можно безопасно коммитить в git
