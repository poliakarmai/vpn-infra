# AGENTS.md — VPN Infra

> Навигация для AI-агентов. VLESS+REALITY VPN с Telegram-ботом продавцом.

## Что это

VPN-инфраструктура: Xray VLESS+REALITY на Keenetic, WireGuard-сервер, Telegram-бот @Poliakarbot для продажи ключей. Администрирование через `admin_key.py`.

## Структура репозитория

```
bot.py              ← Telegram-бот @Poliakarbot (прод: /opt/vpn-seller-bot/bot.py)
admin_key.py        ← выдача/отзыв VLESS-ключей (прод: /opt/vpn-seller-bot/admin_key.py)
requirements.txt    ← зависимости бота
vpn-core/
  vpn-watch.py      ← мониторинг Xray (крон: ~/.hermes/scripts/vpn-watch.py)
  vpn-bot-watch.py  ← watchdog бота (крон: ~/.hermes/scripts/vpn-bot-watch.py)
  config.template.json ← шаблон Xray; рабочий конфиг — /opt/vpn-core/conf/config.json
systemd/            ← юниты (прод: /etc/systemd/system/)
scripts/            ← разовые утилиты (vpn-broadcast.py — рассылка по базе)
openwiki/           ← OpenWiki-документация
```

**Прод — источник правды.** Файлы, которые правятся на месте (`bot.py`, watchdog-скрипты,
юниты), копируются с сервера в репо после правки. Секреты и данные (`.env`, `config.json`,
`*.sqlite`) — только на сервере, в git не попадают.

## Как запускать

```bash
# Бот (системный юнит)
sudo systemctl status vpn-seller-bot

# Выдать ключ (dry-run сначала — покажет ссылку, ничего не запишет)
sudo python3 /opt/vpn-seller-bot/admin_key.py <tg_id> 30 --dry-run
sudo python3 /opt/vpn-seller-bot/admin_key.py <tg_id> 30

# Отозвать: удалить подписку в БД + rebuild_xray
```

## Где что лежит (прод)

| Данные | Путь |
|--------|------|
| Бот .env | `/opt/vpn-seller-bot/.env` (vpn-bot:0600) |
| БД подписок | `/opt/vpn-seller-bot/data/vpn_seller.sqlite` |
| Конфиг Xray | `/opt/vpn-core/conf/config.json` |
| Бэкапы конфига | `/opt/vpn-core/conf/config.json.bak*` |
| Логи | `sudo journalctl -u vpn-core-xray -u vpn-seller-bot` |

## Инварианты

1. **Xray — песочница.** Не трогать системные конфиги без `admin_key.py`.
2. **Пользователи — SSOT в SQLite.** Не дублировать в JSON.
3. **Conntrack overflow → авто-рестарт.** Мониторинг переполнения conntrack.
4. **sudo: systemctl + wg.** Остальные команды по паролю.
5. **`.env` ищем рядом со скриптом**, а не `parent.parent`: `admin_key.py` лежит в `/opt/vpn-seller-bot/` (прод) или в корне репо, `.env` — в `/opt/vpn-seller-bot/.env`. Старый `parent.parent` давал `/opt/.env` → `SERVER_IP not set`.
6. **`--dry-run` не трогает ни БД, ни Xray.** Флаг проверяется ДО `grant_subscription()`: раньше dry-run оставлял активную подписку-мусор, которая при следующем `rebuild_xray()` попадала в `config.json`.
7. **Ключ считается выданным только после живого теста:** локальный xray-клиент с этим uuid → `curl -x socks5h://127.0.0.1:<port> https://api.ipify.org` → `2.27.48.142`.

## Критерии готовности

- [ ] `sudo python3 /opt/vpn-seller-bot/admin_key.py <tg_id> 30 --dry-run` — печатает ссылку, подписок в БД не прибавилось
- [ ] живой тест ключа: `curl` через socks даёт `2.27.48.142`
- [ ] Бот отвечает на /start
- [ ] Xray слушает 4443 и 8445 (`sudo ss -tnlp | grep xray`)
- [ ] WireGuard активен (51820/udp)
