# AGENTS.md — VPN Infra

> Навигация для AI-агентов. VLESS+REALITY VPN с Telegram-ботом продавцом.

## Что это

VPN-инфраструктура: Xray VLESS+REALITY на Keenetic, WireGuard-сервер, Telegram-бот @Poliakarbot для продажи ключей. Администрирование через `admin_key.py`.

## Структура

```
/opt/vpn-seller-bot/
├── admin_key.py         ← Выдача/отзыв VLESS+REALITY ключей
├── bot.py               ← Telegram-бот @Poliakarbot (продажа, Stars+TON)
├── scripts/             ← Скрипты: мониторинг, авто-рестарт, бэкапы
├── data/                ← Данные: пользователи, ключи, статистика
├── backups/             ← Бэкапы конфигов
├── plans/               ← Тарифные планы
├── requirements.txt     ← Зависимости Python
├── ROADMAP.md           ← План развития
├── AGENTS.md            ← Этот файл
└── .gitignore
```

## Ключевые файлы

| Файл | Назначение |
|------|-----------|
| `admin_key.py` | CLI для выдачи ключей, отзыва, просмотра статистики |
| `bot.py` | Telegram-бот: /start, /buy, /status, оплата Stars+TON |
| `scripts/` | Вспомогательные скрипты (мониторинг conntrack, авто-рестарт Xray) |
| `data/` | SQLite/JSON базы пользователей и ключей |

## Как запускать

```bash
# Бот
cd /opt/vpn-seller-bot && source .venv/bin/activate && python3 bot.py

# Выдать ключ
python3 admin_key.py add --user @username --days 30

# Просмотр статистики
python3 admin_key.py stats
```

## Где что лежит

| Данные | Путь |
|--------|------|
| Пользователи | `data/users.db` |
| Конфиги Xray | `/etc/xray/` (песочница) |
| Бэкапы | `backups/` |
| Логи | `journalctl -u xray` |

## Инварианты

1. **Xray — песочница.** Не трогать системные конфиги без `admin_key.py`.
2. **Пользователи — SSOT в SQLite.** Не дублировать в JSON.
3. **Conntrack overflow → авто-рестарт.** Мониторинг переполнения conntrack.
4. **sudo: systemctl + wg.** Остальные команды по паролю.
5. **`.env` ищем рядом со скриптом**, а не `parent.parent`: `admin_key.py` лежит в `/opt/vpn-seller-bot/` (прод) или `scripts/` (репо), `.env` — в `/opt/vpn-seller-bot/.env`. Старый `parent.parent` давал `/opt/.env` → `SERVER_IP not set`.
6. **`--dry-run` не трогает ни БД, ни Xray.** Флаг проверяется ДО `grant_subscription()`: раньше dry-run оставлял активную подписку-мусор, которая при следующем `rebuild_xray()` попадала в `config.json`.
7. **Ключ считается выданным только после живого теста:** локальный xray-клиент с этим uuid → `curl -x socks5h://127.0.0.1:<port> https://api.ipify.org` → `2.27.48.142`.

## Критерии готовности

- [ ] `sudo python3 /opt/vpn-seller-bot/admin_key.py <tg_id> 30 --dry-run` — печатает ссылку, подписок в БД не прибавилось
- [ ] живой тест ключа: `curl` через socks даёт `2.27.48.142`
- [ ] Бот отвечает на /start
- [ ] Xray слушает порт 443
- [ ] WireGuard активен
