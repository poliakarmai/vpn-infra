# VPN Infrastructure

VLESS+REALITY VPN с Telegram-ботом для продажи ключей.

## Структура

```
vpn-core/         — Xray конфигурация и мониторинг
  config.template.json   — шаблон конфига Xray (с плейсхолдерами)
  vpn-watch.py           — мониторинг трафика и соединений
vpn-seller-bot/   — Telegram-бот продажи VPN-ключей
  bot.py                 — основной код бота
  scripts/               — вспомогательные скрипты
  ROADMAP.md             — план развития
```

## Быстрый старт

```bash
cd vpn-seller-bot
pip install -r requirements.txt
# Копируем .env.example → .env и заполняем секреты
cp .env.example .env
python bot.py
```

## Безопасность

- **Никогда не коммитить `.env`, `config.json`, приватные ключи**
- `config.template.json` в репо содержит плейсхолдеры — заменить на реальные ключи при деплое
