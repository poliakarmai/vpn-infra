# AGENTS.md — VPN Infra

> Навигация для AI-агентов. VPN-инфраструктура: VLESS+REALITY + MTProto + WireGuard.

## Что это

Продакшен VPN-инфраструктура на сервере 2.27.48.142 (Хельсинки):
- **Xray** — VLESS+REALITY (порты 4443, 8445)
- **MTProto** — отдельный сервис `mtproto-proxy` (порт 443/TCP)
- **WireGuard** — порт 51820/UDP
- **Telegram-бот @Poliakarbot** — продажа ключей (Stars + CryptoBot), триал 3 дня

## Структура

```
vpn-infra/                      ← ЭТОТ репозиторий (документация + код)
├── vpn-core/
│   ├── config.template.json    ← Шаблон конфига Xray (VLESS 4443 + 8445)
│   └── vpn-watch.py            ← Мониторинг: трафик, клиенты, статус
├── vpn-seller-bot/
│   ├── bot.py                  ← Telegram-бот (~2800 строк)
│   ├── admin_key.py            ← CLI-админка: выдача ключей
│   ├── requirements.txt
│   └── ROADMAP.md
├── openwiki/                   ← OpenWiki-документация
├── systemd/                    ← Systemd-юниты
├── README.md
└── AGENTS.md                   ← Этот файл

/opt/vpn-seller-bot/            ← ПРОДАКШЕН-инсталляция бота
/opt/vpn-core/conf/             ← ПРОДАКШЕН-конфиг Xray
/opt/mtprotoproxy/              ← MTProto прокси (отдельный сервис)
```

## Ключевые файлы

| Файл | Назначение |
|------|-----------|
| `bot.py` | Telegram-бот: оплата (Stars/CryptoBot), выдача VLESS/WG/MTProto |
| `admin_key.py` | CLI: `admin_key.py <tg_id> <days>` — выдать ключ без бота |
| `config.template.json` | Шаблон Xray: VLESS 4443 + 8445 (оба с REALITY) |
| `vpn-watch.py` | Мониторинг трафика и подключений |

## Продакшен-сервисы

```bash
# Xray
sudo systemctl status vpn-core-xray

# Бот (СИСТЕМНЫЙ юнит, не --user!)
sudo systemctl status vpn-seller-bot

# MTProto прокси
sudo systemctl status mtproto-proxy
```

**⚠️ Бот — системный юнит.** `systemctl --user status vpn-seller-bot` его НЕ видит. Всегда `sudo systemctl`.

## Где что лежит (продакшен)

| Данные | Место |
|--------|-------|
| Конфиг Xray | `/opt/vpn-core/conf/config.json` |
| Шаблон Xray | `/opt/vpn-core/conf/config.template.json` |
| Бот .env | `/opt/vpn-seller-bot/.env` |
| БД бота | `/opt/vpn-seller-bot/data/vpn_seller.sqlite` |
| MTProto конфиг | `/opt/mtprotoproxy/config.py` |
| Логи Xray | `sudo journalctl -u vpn-core-xray` |
| Логи бота | `sudo journalctl -u vpn-seller-bot` |

## Инварианты

1. **VLESS-ссылки ОБЯЗАНЫ содержать:**
   - `headerType=none` — без него клиенты не подключаются (V2RayTun, Streisand)
   - `encryption=none`, `fp=firefox`, `spx=%2F`, `allowInsecure=1`
   - Проверять во ВСЕХ трёх функциях: `build_vless_link()` (main), `build_vless_backup_link()`, `admin_key.py`
2. **MTProto — отдельный сервис, не в Xray.** Xray 26.x не поддерживает MTProto.
3. **Конфиг Xray — не в репозитории.** В Git только шаблон. `config.json` в `/opt/`.
4. **rebuild_xray() синхронизирует ВСЕ inbounds**, не только [0].
5. **Бот — системный юнит.** Preflight.py его не видит.
6. **PBK проверять через криптографию.** Не доверять `.env` — вычислить из privateKey Xray.

## Конвенции

- Python 3.11+
- VLESS+REALITY (не XTLS)
- Оплата: Telegram Stars (XTR) + CryptoBot (TON/USDT)
- SSH: порт 2091 (не 22)
- Hermes в песочнице — `/opt/` доступен только через `sudo`

## Критерии готовности

- [ ] `sudo systemctl is-active vpn-core-xray vpn-seller-bot mtproto-proxy` — все active
- [ ] `sudo python3 vpn-seller-bot/admin_key.py list` → показывает клиентов
- [ ] `sudo grep -c headerType vpn-seller-bot/bot.py` → 2
- [ ] `sudo grep -c headerType vpn-seller-bot/admin_key.py` → 1
