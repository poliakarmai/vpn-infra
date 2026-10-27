# VPN Infrastructure

VLESS+REALITY VPN с Telegram-ботом для продажи ключей. Продакшен на 2.27.48.142 (Хельсинки).

## Протоколы

| Протокол | Порты | Статус |
|----------|-------|--------|
| VLESS+REALITY (основной) | 4443/TCP | ✅ |
| VLESS+REALITY (резервный) | 8445/TCP | ✅ |
| MTProto Proxy | 443/TCP | ✅ (отдельный сервис) |
| WireGuard | 51820/UDP | ✅ |

## Возможности бота (@Poliakarbot)

- **VLESS+REALITY** ключи (30/90/180 дней)
- **WireGuard/AmneziaWG** конфиги
- **MTProto прокси** для Telegram
- **Оплата:** Telegram Stars (⭐ XTR) + CryptoBot (💎 TON/USDT)
- **Триал:** 3 дня бесплатно
- **Реферальная программа:** +7 дней за друга
- **Авто-продление** с уведомлениями за 72ч и 24ч до истечения

## Цены

| Тариф | USDT | Stars (XTR) |
|-------|------|-------------|
| VLESS 30 дней | $2.00 | 160 ⭐ |
| VLESS 90 дней | $5.40 | 430 ⭐ |
| VLESS 180 дней | $10.00 | 795 ⭐ |
| WireGuard 30 дней | $1.00 | — |
| MTProto 30 дней | $0.50 | — |

## Структура

```
bot.py              — Telegram-бот @Poliakarbot (прод: /opt/vpn-seller-bot/bot.py)
admin_key.py        — CLI выдачи ключей (прод: /opt/vpn-seller-bot/admin_key.py)
requirements.txt    — зависимости бота
vpn-core/
  vpn-watch.py      — мониторинг Xray (крон: ~/.hermes/scripts/vpn-watch.py)
  vpn-bot-watch.py  — watchdog бота (крон: ~/.hermes/scripts/vpn-bot-watch.py)
  config.template.json — шаблон Xray (реальный конфиг в /opt/vpn-core/conf/)
systemd/            — юниты (прод: /etc/systemd/system/)
scripts/            — разовые утилиты (vpn-broadcast.py — рассылка по базе)
openwiki/           — OpenWiki-документация
```

**Прод — источник правды.** Репо синхронизируется с сервера, не наоборот: файлы,
которые правятся на месте (`bot.py`, watchdog-скрипты, юниты), копируются в репо
после правки. Секреты и данные (`.env`, `config.json`, `*.sqlite`) — только на сервере.

## Быстрый старт (разработка)

```bash
pip install -r requirements.txt
cp .env.example .env  # заполнить TELEGRAM_BOT_TOKEN, CRYPTOBOT_TOKEN, SERVER_IP, etc.
python3 bot.py
```

## Деплой (продакшен)

```bash
# Системные юниты (НЕ пользовательские!)
sudo systemctl status vpn-core-xray     # Xray
sudo systemctl status vpn-seller-bot    # Бот (от vpn-bot)
sudo systemctl status mtproto-proxy     # MTProto прокси
```

## Безопасность

- **Никогда не коммитить** `.env`, `config.json`, приватные ключи
- `config.template.json` содержит плейсхолдеры
- Все секреты в `/opt/vpn-seller-bot/.env` (владелец: vpn-bot, 0600)

## Лицензия

MIT — Alexey Polyakov, 2026
