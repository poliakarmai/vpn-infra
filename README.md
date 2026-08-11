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
vpn-core/           — Xray конфигурация и мониторинг
vpn-seller-bot/     — Telegram-бот продажи ключей
systemd/            — Systemd-юниты
openwiki/           — OpenWiki-документация
```

## Быстрый старт (разработка)

```bash
cd vpn-seller-bot
pip install -r requirements.txt
cp .env.example .env  # заполнить TELEGRAM_BOT_TOKEN, CRYPTOBOT_TOKEN, SERVER_IP, etc.
python bot.py
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
