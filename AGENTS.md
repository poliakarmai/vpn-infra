# AGENTS.md — VPN Infra

> Навигация для AI-агентов. VPN-инфраструктура на VLESS+REALITY.

## Что это

Полноценная VPN-инфраструктура: Xray-сервер (VLESS+REALITY), Telegram-бот для продажи ключей, админ-панель, мониторинг.  
Продакшен: ~10 активных клиентов.

## Структура

```
vpn-infra/
├── vpn-core/
│   ├── config.template.json   ← Шаблон конфига Xray
│   └── vpn-watch.py           ← Мониторинг: трафик, клиенты, статус
├── vpn-seller-bot/
│   ├── bot.py                 ← Telegram-бот для продажи VPN
│   ├── admin_key.py           ← Админка: создание/удаление ключей
│   ├── requirements.txt       ← Зависимости
│   └── ROADMAP.md             ← План развития
├── .gitignore
└── README.md
```

## Ключевые файлы

| Файл | Назначение |
|------|-----------|
| `vpn-watch.py` | Мониторинг сервера: трафик (RX/TX), подключённые клиенты, статус сервиса Xray |
| `bot.py` | Telegram-бот: продажа ключей, оплата через Telegram Stars, выдача конфигов |
| `admin_key.py` | CLI-админка: `list`, `add <user>`, `remove <user>`, `usage <user>` |

## Как запускать

```bash
# Мониторинг
python3 vpn-core/vpn-watch.py

# Telegram-бот
cd vpn-seller-bot
python3 bot.py

# Админка (выдача ключа)
python3 admin_key.py add new_user_123
python3 admin_key.py list
python3 admin_key.py usage new_user_123
```

## Как развернуть с нуля

```bash
cd ~/vpn-infra
# Установка Xray (см. README.md)
bash install.sh
# Копировать config.template.json → /usr/local/etc/xray/config.json
# Подставить свой REALITY private key + short_id
systemctl start xray
```

## Где что лежит

| Данные | Место |
|--------|-------|
| Конфиг Xray | `/usr/local/etc/xray/config.json` |
| Ключи клиентов | Внутри config.json (clients[]) |
| Логи Xray | `/var/log/xray/` |

## Конвенции

- Python 3.11+
- VLESS+REALITY (не VLESS+XTLS — лучше обходит DPI)
- Ключи клиентов — UUID + short_id
- Telegram Stars для оплаты (fragment.com → TON)
- Безопасность: fail2ban, порт SSH на 29001 (не 22)

## Инварианты

1. **VLESS+REALITY, не XTLS.** REALITY лучше обходит DPI.
2. **Ключи = UUID + short_id.** Никаких паролей.
3. **Оплата через Telegram Stars.** Не TON напрямую — через fragment.com.
4. **Конфиг Xray — не в репозитории.** `config.json` в `/usr/local/etc/xray/`, в Git только шаблон.

## Критерии готовности

- [ ] `systemctl status xray` — active
- [ ] `python3 vpn-core/vpn-watch.py` — без ошибок
- [ ] `python3 admin_key.py list` — показывает клиентов
