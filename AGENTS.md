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

## Критерии готовности

- [ ] `python3 admin_key.py stats` — показывает статистику
- [ ] Бот отвечает на /start
- [ ] Xray слушает порт 443
- [ ] WireGuard активен
