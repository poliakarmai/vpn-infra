import asyncio
import json
import logging
import os
import signal
import sqlite3
import subprocess
import time
import uuid
import shutil

import httpx
import qrcode

# Global lock to serialize access provisioning / x-ui DB writes
PROVISION_LOCK = asyncio.Lock()
from aiogram import Bot, Dispatcher, F
from aiogram.filters import CommandStart
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message, BufferedInputFile
from dotenv import load_dotenv

load_dotenv()
logging.basicConfig(level=logging.INFO)
log = logging.getLogger("vpn-seller")

BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()
CRYPTOBOT_TOKEN = os.environ.get("CRYPTOBOT_TOKEN", "").strip()

PRICE_USDT_30 = float(os.environ.get("PRICE_USDT_30", os.environ.get("PRICE_USDT", "2.0")))
PRICE_USDT_90 = float(os.environ.get("PRICE_USDT_90", str(PRICE_USDT_30 * 2.7)))
PRICE_USDT_180 = float(os.environ.get("PRICE_USDT_180", str(PRICE_USDT_30 * 5.0)))
PRICE_TON_MIN = float(os.environ.get("PRICE_TON_MIN", "0.1"))

SUB_DAYS_30 = 30
SUB_DAYS_90 = 90
SUB_DAYS_180 = 180

TRIAL_MINUTES = int(os.environ.get("TRIAL_MINUTES", "30"))
TRIAL_MAX_PER_USER = int(os.environ.get("TRIAL_MAX_PER_USER", "1"))

# Telegram Stars prices (1 Star ≈ $0.0126 USD)
STARS_PRICE_30 = int(os.environ.get("STARS_PRICE_30", "160"))   # ~$2.00
STARS_PRICE_90 = int(os.environ.get("STARS_PRICE_90", "430"))   # ~$5.40
STARS_PRICE_180 = int(os.environ.get("STARS_PRICE_180", "795")) # ~$10.00

ADMIN_IDS = {int(x) for x in os.environ.get("ADMIN_IDS", "319665243").split(",") if x.strip().isdigit()}
REFERRAL_BONUS_DAYS = int(os.environ.get("REFERRAL_BONUS_DAYS", "7"))

DB_PATH = os.environ.get("DB_PATH", "./data/vpn_seller.sqlite")
PANEL_DB_PATH = os.environ.get("PANEL_DB_PATH", "/opt/3x-ui/x-ui.db")  # legacy / unused in variant A

XRAY_CONFIG_PATH = os.environ.get("XRAY_CONFIG_PATH", "/opt/vpn-core/conf/config.json")
XRAY_SERVICE = os.environ.get("XRAY_SERVICE", "vpn-core-xray")

SERVER_IP = os.environ.get("SERVER_IP", "").strip()
VLESS_PORT = int(os.environ.get("VLESS_PORT", "4443"))
VLESS_SNI = os.environ.get("VLESS_SNI", "www.cloudflare.com").strip()
VLESS_FINGERPRINT = os.environ.get("VLESS_FINGERPRINT", "chrome").strip()
VLESS_PBK = os.environ.get("VLESS_PBK", "").strip()
VLESS_SID = os.environ.get("VLESS_SID", "").strip()

# MTProto Proxy
PROXY_SERVER = os.environ.get("PROXY_SERVER", SERVER_IP).strip()
PROXY_PORT = int(os.environ.get("PROXY_PORT", "8443"))
PROXY_SECRET = os.environ.get("PROXY_SECRET", "").strip()

# Backup Reality port (Level 2 anti-censorship)
VLESS_BACKUP_PORT = int(os.environ.get("VLESS_BACKUP_PORT", "8445"))
VLESS_BACKUP_SNI = os.environ.get("VLESS_BACKUP_SNI", "www.microsoft.com").strip()
VLESS_BACKUP_PBK = os.environ.get("VLESS_BACKUP_PBK", "").strip()
VLESS_BACKUP_SID = os.environ.get("VLESS_BACKUP_SID", "").strip()

# WireGuard / AmneziaWG
WG_PORT = int(os.environ.get("WG_PORT", "51820"))
WG_SUBNET = os.environ.get("WG_SUBNET", "10.88.0")
WG_SERVER_PUBKEY = os.environ.get("WG_SERVER_PUBKEY", "").strip()
WG_SERVER_PRIVKEY_PATH = os.environ.get("WG_SERVER_PRIVKEY_PATH", "/etc/wireguard/server_private.key")
WG_CONFIG_PATH = os.environ.get("WG_CONFIG_PATH", "/etc/wireguard/wg0.conf")
# Amnezia obfuscation params (client-side, included in config for Amnezia clients)
WG_AMNEZIA_JC = int(os.environ.get("WG_AMNEZIA_JC", "4"))
WG_AMNEZIA_JMIN = int(os.environ.get("WG_AMNEZIA_JMIN", "40"))
WG_AMNEZIA_JMAX = int(os.environ.get("WG_AMNEZIA_JMAX", "70"))
WG_AMNEZIA_S1 = int(os.environ.get("WG_AMNEZIA_S1", "10"))
WG_AMNEZIA_S2 = int(os.environ.get("WG_AMNEZIA_S2", "30"))
WG_AMNEZIA_H1 = int(os.environ.get("WG_AMNEZIA_H1", "10150"))
WG_AMNEZIA_H2 = int(os.environ.get("WG_AMNEZIA_H2", "20150"))
WG_AMNEZIA_H3 = int(os.environ.get("WG_AMNEZIA_H3", "30150"))
WG_AMNEZIA_H4 = int(os.environ.get("WG_AMNEZIA_H4", "40150"))

# ── i18n: All user-facing strings in EN / RU ──
T = {
    # ── Keyboard buttons ──
    "btn_trial":            {"ru": "🎁 Попробовать бесплатно",     "en": "🎁 Free Trial"},
    "btn_buy_30":           {"ru": "Купить 30 дней",              "en": "Buy 30 days"},
    "btn_buy_90":           {"ru": "Купить 90 дней (-10%)",       "en": "Buy 90 days (-10%)"},
    "btn_buy_180":          {"ru": "Купить 180 дней (-20%)",      "en": "Buy 180 days (-20%)"},
    "btn_promo":            {"ru": "Промокод",                    "en": "Promo Code"},
    "btn_wg_access":        {"ru": "🔒 WireGuard",                 "en": "🔒 WireGuard"},
    "btn_xkeen":            {"ru": "🌀 Keenetic",                  "en": "🌀 Keenetic"},
    "btn_proxy":            {"ru": "🍃 Прокси TG ($0.50)",         "en": "🍃 TG Proxy ($0.50)"},
    "btn_referral":         {"ru": "🎁 Пригласить друга",          "en": "🎁 Invite a Friend"},
    "btn_my_access":        {"ru": "Мой QR / доступ",             "en": "My QR / Access"},
    "btn_help":             {"ru": "Инструкции",                  "en": "Help"},
    "btn_support":          {"ru": "Поддержка",                   "en": "Support"},
    "btn_lang":             {"ru": "🌐 Язык",                      "en": "🌐 Language"},

    # ── Main screen ──
    "main_title":           {"ru": "VPN подписка (VLESS+REALITY)",  "en": "VPN Subscription (VLESS+REALITY)"},
    "main_subtitle":        {"ru": "Без лишних настроек: QR или ссылка.", "en": "No complex setup: QR or link."},
    "main_payment":         {"ru": "Оплата: TON (цена считается от USDT по курсу).", "en": "Payment: TON (priced from USDT at current rate)."},
    "main_status_active":   {"ru": "Статус: ✅ активна до",         "en": "Status: ✅ active until"},
    "main_status_inactive": {"ru": "Статус: ❌ нет активной подписки", "en": "Status: ❌ no active subscription"},
    "main_renew_cta":       {"ru": "Продление — в 1 клик: выбери 30/90/180 дней ниже.", "en": "Renew in 1 click: choose 30/90/180 days below."},
    "main_buy_cta":         {"ru": "Выбери тариф (30/90/180) — доступ придёт автоматически после оплаты.", "en": "Choose a plan (30/90/180) — access delivered automatically after payment."},
    "main_last_invoice":    {"ru": "Последний счёт:",              "en": "Last invoice:"},
    "main_plans_header":    {"ru": "Тарифы (эквивалент в USDT):",   "en": "Plans (USDT equivalent):"},

    # ── Trial ──
    "trial_used":           {"ru": "Триал уже использован. Выбери тариф 30/90/180 дней.", "en": "Trial already used. Choose a 30/90/180 day plan."},
    "trial_activated":      {"ru": "🎁 Триал активирован на {} минут.", "en": "🎁 Trial activated for {} minutes."},
    "trial_active_until":   {"ru": "Активен до:",                  "en": "Active until:"},
    "trial_like_it":        {"ru": "Если понравилось — выбери тариф 30/90/180 дней на главном экране.", "en": "If you liked it — choose a 30/90/180 day plan on the main screen."},

    # ── Payment / Invoice ──
    "invoice_created":      {"ru": "Счёт создан: {} TON\nОплата: {}", "en": "Invoice created: {} TON\nPay: {}"},
    "invoice_tariff":       {"ru": "Тариф: {} дней",               "en": "Plan: {} days"},
    "invoice_promo":        {"ru": "Промокод: {} ({})",            "en": "Promo: {} ({})"},
    "invoice_bonus":        {"ru": "Бонус: +{} дней",              "en": "Bonus: +{} days"},
    "invoice_autocheck":    {"ru": "Я проверяю оплату автоматически ~{} мин.", "en": "I auto-check payment for ~{} min."},
    "payment_confirmed":    {"ru": "✅ Оплата подтверждена. Продлил на {} дней.", "en": "✅ Payment confirmed. Extended by {} days."},
    "payment_bonus":        {"ru": "Бонус: +{} дней",              "en": "Bonus: +{} days"},
    "payment_active_until": {"ru": "Подписка активна до:",         "en": "Subscription active until:"},
    "payment_reimport":     {"ru": "Если не работает: удали старый профиль в клиенте и импортируй QR заново.", "en": "Not working? Delete old profile in client and re-import QR."},
    "no_invoices":          {"ru": "Нет счетов. Нажми Купить.",    "en": "No invoices. Press Buy."},
    "invoice_not_found":    {"ru": "Не нашёл счёт в CryptoBot. Создай новый.", "en": "Invoice not found on CryptoBot. Create a new one."},
    "invoice_status":       {"ru": "Статус: {}. Если оплатил — подожди немного (обычно до минуты) или просто подожди — авто-проверка тоже работает.", "en": "Status: {}. If you paid — wait a bit (usually up to a minute) or just wait — auto-check is also running."},
    "payment_processed":    {"ru": "Оплата уже обработана, доступ выдан. Нажми «Мой QR / доступ».", "en": "Payment already processed, access granted. Press \"My QR / Access\"."},
    "autocheck_timeout":    {"ru": "Автопроверка остановлена (таймаут). Если оплатил — нажми «Проверить оплату».", "en": "Auto-check stopped (timeout). If you paid — press \"Check Payment\"."},
    "autocheck_error":      {"ru": "Автопроверка оплаты остановлена из-за ошибки. Нажми «Проверить оплату».", "en": "Auto-check stopped due to error. Press \"Check Payment\"."},

    # ── My Access ──
    "no_active_sub":        {"ru": "Нет активной подписки. Нажми Купить.", "en": "No active subscription. Press Buy."},
    "your_access":          {"ru": "Твой текущий доступ.",          "en": "Your current access."},
    "no_active_sub_wg":     {"ru": "Нет активной подписки. Сначала оплати VLESS тариф.", "en": "No active subscription. Buy a VLESS plan first."},

    # ── WireGuard ──
    "wg_header":            {"ru": "🔒 **WireGuard / AmneziaWG**",  "en": "🔒 **WireGuard / AmneziaWG**"},
    "wg_header_new":        {"ru": "🔒 **WireGuard / AmneziaWG — ключ создан!**", "en": "🔒 **WireGuard / AmneziaWG — key created!**"},
    "wg_active_until":      {"ru": "Активен до:",                  "en": "Active until:"},
    "wg_std_header":        {"ru": "**Стандартный WireGuard:**\n• WireGuard (iOS/Android/Desktop)\n• NekoBox, v2rayNG", "en": "**Standard WireGuard:**\n• WireGuard (iOS/Android/Desktop)\n• NekoBox, v2rayNG"},
    "wg_awg_header":        {"ru": "**AmneziaWG (с обфускацией):**\n• AmneziaVPN\n• NekoBox (Amnezia-режим)", "en": "**AmneziaWG (with obfuscation):**\n• AmneziaVPN\n• NekoBox (Amnezia mode)"},
    "wg_qr_note":           {"ru": "QR — стандартный WireGuard.\nКонфиг AmneziaWG — текстом ниже:", "en": "QR — standard WireGuard.\nAmneziaWG config — below as text:"},
    "wg_new_note":          {"ru": "QR — стандартный WireGuard. Конфиги ниже.", "en": "QR — standard WireGuard. Configs below."},
    "wg_error":             {"ru": "❌ Ошибка добавления WireGuard:", "en": "❌ WireGuard add error:"},
    "wg_error_generic":     {"ru": "❌ Ошибка:",                    "en": "❌ Error:"},

    # ── XKeen ──
    "xkeen_caption":        {"ru": "🌀 **XKeen (Keenetic) — конфиг VLESS+REALITY**\nАктивен до: {}\n\n**Инструкция:**\n1) Установи XKeen из каталога пакетов Keenetic\n2) Импортируй конфиг (этот файл)\n3) Включи\n\nФайл уже готов к импорту — просто загрузи его в XKeen.", "en": "🌀 **XKeen (Keenetic) — VLESS+REALITY config**\nActive until: {}\n\n**Instructions:**\n1) Install XKeen from the Keenetic package catalog\n2) Import the config (this file)\n3) Enable\n\nThe file is ready to import — just upload it to XKeen."},

    # ── Referral ──
    "ref_title":            {"ru": "🎁 **Реферальная программа**",   "en": "🎁 **Referral Program**"},
    "ref_desc":             {"ru": "Пригласи друга — получи +{} дней VPN за каждого, кто оплатит подписку.", "en": "Invite a friend — get +{} VPN days for each who pays."},
    "ref_your_link":        {"ru": "Твоя ссылка:",                  "en": "Your link:"},
    "ref_invited":          {"ru": "Приглашено: {} чел.",          "en": "Invited: {}"},
    "ref_bonus_note":       {"ru": "Бонус начисляется автоматически при первой оплате реферала.", "en": "Bonus is credited automatically on first payment by referral."},
    "ref_bonus_msg":        {"ru": "🎁 Твой друг оплатил подписку! +{} дней VPN подарено.\nПодписка продлена до: {}", "en": "🎁 Your friend paid for a subscription! +{} VPN days gifted.\nSubscription extended to: {}"},

    # ── Help ──
    "help_title":           {"ru": "Инструкция по подключению",    "en": "Connection Guide"},
    "help_android":         {"ru": "Android:\n1) Установи: v2rayNG или NekoBox\n2) В боте нажми «Мой QR / доступ»\n3) В приложении: Import/Scan QR или вставь vless-ссылку\n4) Включи профиль", "en": "Android:\n1) Install: v2rayNG or NekoBox\n2) In bot: press \"My QR / Access\"\n3) In app: Import/Scan QR or paste vless link\n4) Enable profile"},
    "help_ios":             {"ru": "iPhone (iOS):\n1) Установи: Streisand или Shadowrocket (если есть)\n2) Импортируй QR/ссылку из «Мой QR / доступ»\n3) Включи профиль", "en": "iPhone (iOS):\n1) Install: Streisand or Shadowrocket (if available)\n2) Import QR/link from \"My QR / Access\"\n3) Enable profile"},
    "help_windows":         {"ru": "Windows:\n1) Установи: v2rayN\n2) Импорт: vless-ссылка или QR\n3) Включи системный прокси/режим TUN (если нужно), затем подключись", "en": "Windows:\n1) Install: v2rayN\n2) Import: vless link or QR\n3) Enable system proxy/TUN mode (if needed), then connect"},
    "help_macos":           {"ru": "macOS:\n1) Установи: Clash Verge / sing-box / FoXray (любой клиент с VLESS+REALITY)\n2) Импортируй QR/ссылку\n3) Подключись", "en": "macOS:\n1) Install: Clash Verge / sing-box / FoXray (any client with VLESS+REALITY)\n2) Import QR/link\n3) Connect"},
    "help_reimport":        {"ru": "Если не работает: удали старый профиль и импортируй QR заново.", "en": "Not working? Delete old profile and re-import QR."},

    # ── Support ──
    "support_msg":          {"ru": "Поддержка: напишите @Cryptoram", "en": "Support: contact @Cryptoram"},
    "support_xray_fail":    {"ru": "⚠️ VPN-сервис сейчас не перезапустился автоматически. Напиши в поддержку.", "en": "⚠️ VPN service did not restart automatically. Contact support."},

    # ── MTProto Proxy ──
    "proxy_title":          {"ru": "🍃 MTProto Прокси для Telegram", "en": "🍃 MTProto Proxy for Telegram"},
    "proxy_desc":           {"ru": "• Цена: **$0.50** (эквивалент в TON по курсу)\n• Срок: 30 дней\n• Работает в обход блокировок Telegram\n• ⚠️ Прокси может иногда отваливаться (DPI). Это бюджетный вариант — без гарантии 100% uptime.\n• Если не работает — можно вернуться к VLESS VPN.", "en": "• Price: **$0.50** (TON equivalent at rate)\n• Duration: 30 days\n• Bypasses Telegram blocks\n• ⚠️ Proxy may occasionally drop (DPI). Budget option — no 100% uptime guarantee.\n• If it stops working — you can switch back to VLESS VPN."},
    "proxy_access":         {"ru": "🔑 Твой MTProto прокси:\n\nСервер: **{server}**\nПорт: **{port}**\nСекрет: `{secret}`\n\n🔗 Ссылка: tg://proxy?server={server}&port={port}&secret={secret}\n\n🌀 **Keenetic роутер:**\nИнтернет → Прокси-сервер → Добавить\nТип: MTProto\nСервер: {server}\nПорт: {port}\nСекрет: {secret}\n\nАктивен до: {expires}\n\n⚠️ Если перестал — порт 443.", "en": "🔑 Your MTProto proxy:\n\nServer: **{server}**\nPort: **{port}**\nSecret: `{secret}`\n\n🔗 Link: tg://proxy?server={server}&port={port}&secret={secret}\n\n🌀 **Keenetic router:**\nInternet → Proxy server → Add\nType: MTProto\nServer: {server}\nPort: {port}\nSecret: {secret}\n\nActive until: {expires}\n\n⚠️ If down — port 443."},
    "proxy_no_sub":         {"ru": "❌ Нет активной подписки на прокси. Нажми кнопку чтобы оплатить.", "en": "❌ No active proxy subscription. Press button to pay."},

    "promo_usage":          {"ru": "Использование: /promo CODE",   "en": "Usage: /promo CODE"},
    "promo_enter":          {"ru": "Введи промокод командой: /promo CODE", "en": "Enter promo code with: /promo CODE"},
    "promo_activated":      {"ru": "Промокод активирован:",        "en": "Promo code activated:"},
    "promo_type":           {"ru": "Тип:",                         "en": "Type:"},
    "promo_value":          {"ru": "Значение:",                    "en": "Value:"},
    "promo_now_buy":        {"ru": "Теперь выбирай тариф кнопками (30/90/180) — скидка/бонус применится автоматически.", "en": "Now choose a plan with buttons (30/90/180) — discount/bonus applies automatically."},
    "promo_not_found":      {"ru": "Промокод не найден.",          "en": "Promo code not found."},
    "promo_expired":        {"ru": "Промокод истёк.",              "en": "Promo code expired."},
    "promo_limit_reached":  {"ru": "Лимит использований промокода исчерпан.", "en": "Promo code usage limit reached."},
    "promo_already_used":   {"ru": "Ты уже использовал этот промокод.", "en": "You already used this promo code."},

    # ── Admin ──
    "admin_denied":         {"ru": "⛔ Доступ запрещён.",           "en": "⛔ Access denied."},
    "admin_stats_title":    {"ru": "📊 **Админ-статистика**",        "en": "📊 **Admin Stats**"},
    "admin_stats_users":    {"ru": "👥 Пользователей:",             "en": "👥 Users:"},
    "admin_stats_active":   {"ru": "✅ Активных подписок:",          "en": "✅ Active subs:"},
    "admin_stats_paid":     {"ru": "💰 Оплаченных счетов:",          "en": "💰 Paid invoices:"},
    "admin_stats_revenue":  {"ru": "💵 Сумма оплат:",               "en": "💵 Revenue:"},
    "admin_stats_traffic":  {"ru": "📡 Трафик (последний месяц):",   "en": "📡 Traffic (last month):"},
    "admin_issue_usage":    {"ru": "Использование: /admin issue <tg_id> <days>", "en": "Usage: /admin issue <tg_id> <days>"},
    "admin_issue_must_be_num": {"ru": "tg_id и days должны быть числами", "en": "tg_id and days must be numbers"},
    "admin_issue_done":     {"ru": "✅ Ключ выдан tg={}\nUUID: {}\nДней: {}\nИстекает: {}\nXray reload: {}", "en": "✅ Key issued tg={}\nUUID: {}\nDays: {}\nExpires: {}\nXray reload: {}"},
    "admin_issue_user_msg": {"ru": "🎁 Администратор выдал тебе VPN-доступ на {} дней!\nАктивен до: {}\n\nНажми «Мой QR / доступ» в боте чтобы получить ключ.", "en": "🎁 Admin granted you VPN access for {} days!\nActive until: {}\n\nPress \"My QR / Access\" in the bot to get your key."},
    "admin_revoke_usage":   {"ru": "Использование: /admin revoke <tg_id>", "en": "Usage: /admin revoke <tg_id>"},
    "admin_revoke_must_be_num": {"ru": "tg_id должен быть числом",  "en": "tg_id must be a number"},
    "admin_revoke_done":    {"ru": "🔕 Подписки tg={} деактивированы. Xray reload: {}", "en": "🔕 Subscriptions tg={} deactivated. Xray reload: {}"},
    "admin_broadcast_usage": {"ru": "Использование: /admin broadcast <текст>", "en": "Usage: /admin broadcast <text>"},
    "admin_broadcast_sent": {"ru": "📢 Рассылка отправлена: {}/{}", "en": "📢 Broadcast sent: {}/{}"},
    "admin_health_title":   {"ru": "🏥 **Health Check**",          "en": "🏥 **Health Check**"},
    "admin_health_bot":     {"ru": "vpn-seller-bot: ✅ active",    "en": "vpn-seller-bot: ✅ active"},
    "admin_health_memory":  {"ru": "Память:",                      "en": "Memory:"},
    "admin_help":           {"ru": "📋 **Админ-команды:**\n/admin stats — статистика\n/admin traffic — трафик (live)\n/admin health — health-check\n/admin issue <tg_id> <days> — выдать ключ\n/admin revoke <tg_id> — отозвать\n/admin broadcast <текст> — рассылка\n/admin backup — создать бэкап\n/admin restore [файл] — список/восстановление", "en": "📋 **Admin Commands:**\n/admin stats — stats\n/admin traffic — traffic (live)\n/admin health — health-check\n/admin issue <tg_id> <days> — issue key\n/admin revoke <tg_id> — revoke\n/admin broadcast <text> — broadcast\n/admin backup — create backup\n/admin restore [file] — list/restore"},

    # ── Expiry notifications ──
    "expiry_days":          {"ru": "🌊 Привет! Твоя VPN-подписка истекает через {} дн. ({}).\nПродли сейчас — чтобы не остаться без доступа.", "en": "🌊 Hi! Your VPN subscription expires in {} days ({}).\nRenew now so you don't lose access."},
    "expiry_tomorrow":      {"ru": "⏳ VPN-подписка истекает завтра ({}).\nПродли сейчас, и всё будет как море — гладко.", "en": "⏳ VPN subscription expires tomorrow ({}).\nRenew now and stay connected."},
    "expiry_hours":         {"ru": "⚠️ VPN-подписка истекает через {} ч. ({})!\nПрямо сейчас продли — чтобы не прервался доступ.", "en": "⚠️ VPN subscription expires in {} h. ({})!\nRenew right now so access isn't interrupted."},

    # ── Inline query ──
    "inline_my_access":     {"ru": "🔑 Мой VPN-доступ",            "en": "🔑 My VPN Access"},
    "inline_active_desc":   {"ru": "Активен до:",                  "en": "Active until:"},
    "inline_access_msg":    {"ru": "🔑 Твой VPN-доступ (VLESS+REALITY)\n\n🔹 **Основной (cloudflare):**\n`{}`\n\n🔸 **Резервный (microsoft):**\n`{}`\n\nАктивен до: {}\n\n_Если не работает — переключись на резервный._", "en": "🔑 Your VPN Access (VLESS+REALITY)\n\n🔹 **Primary (cloudflare):**\n`{}`\n\n🔸 **Backup (microsoft):**\n`{}`\n\nActive until: {}\n\n_If one doesn't work — switch to the other._"},
    "inline_my_qr":         {"ru": "📱 Мой QR-код",                "en": "📱 My QR Code"},
    "inline_qr_desc":       {"ru": "QR-код для импорта в клиент",  "en": "QR code for client import"},
    "inline_qr_msg":        {"ru": "📱 Отсканируй QR в боте @poliakabot → «Мой QR / доступ»\nАктивен до: {}", "en": "📱 Scan QR in @poliakabot bot → \"My QR / Access\"\nActive until: {}"},
    "inline_no_sub_title":  {"ru": "🔒 Нет активной подписки",      "en": "🔒 No active subscription"},
    "inline_no_sub_desc":   {"ru": "Перейди в бота чтобы приобрести", "en": "Open the bot to purchase"},
    "inline_no_sub_msg":    {"ru": "🔒 Нет активной VPN-подписки. Перейди в @poliakabot чтобы приобрести.", "en": "🔒 No active VPN subscription. Open @poliakabot to purchase."},

    # ── Config not set ──
    "config_not_set":       {"ru": "Бот ещё не настроен (SERVER_IP/VLESS_PBK/VLESS_SID).", "en": "Bot not configured yet (SERVER_IP/VLESS_PBK/VLESS_SID)."},

    # ── Health / Misc ──
    "health_public":        {"ru": "🏥 VPN сервис работает.",       "en": "🏥 VPN service is running."},
    "traffic_header":       {"ru": "📊 Трафик:",                   "en": "📊 Traffic:"},

    # ── Language selection ──
    "lang_select":          {"ru": "🌐 Выбери язык / Choose language:", "en": "🌐 Выбери язык / Choose language:"},
    "lang_set_ru":          {"ru": "✅ Язык: Русский",              "en": "✅ Language: Russian"},
    "lang_set_en":          {"ru": "✅ Language: English",          "en": "✅ Language: English"},

    # ── Invoice hidden message ──
    "invoice_hidden_msg":   {"ru": "После оплаты доступ выдастся автоматически. Если нет — нажми: Проверить оплату", "en": "Access granted automatically after payment. If not — press: Check Payment"},

    # ── Telegram Stars ──
    "stars_pay":            {"ru": "⭐ Telegram Stars",               "en": "⭐ Telegram Stars"},
    "stars_desc":           {"ru": "Оплата звездами Telegram — быстро и без криптокошелька.", "en": "Pay with Telegram Stars — fast, no crypto wallet needed."},
    "stars_invoice_title":  {"ru": "VPN {} дней",                     "en": "VPN {} days"},
    "stars_invoice_desc":   {"ru": "VLESS+REALITY VPN на {} дней. Доступ выдаётся автоматически после оплаты.", "en": "VLESS+REALITY VPN for {} days. Access granted automatically after payment."},
    "stars_payment_confirmed": {"ru": "✅ Оплата звездами подтверждена! Telegram charge id: {}", "en": "✅ Stars payment confirmed! Telegram charge id: {}"},
    "stars_error":          {"ru": "❌ Ошибка при создании счёта Stars: {}", "en": "❌ Stars invoice error: {}"},
    "payment_method_choice": {"ru": "Выбери способ оплаты:",          "en": "Choose payment method:"},
    "btn_pay_stars":        {"ru": "⭐ Оплатить звездами",             "en": "⭐ Pay with Stars"},
    "btn_pay_ton":          {"ru": "💎 TON (CryptoBot)",               "en": "💎 TON (CryptoBot)"},

    # ── /test diagnostics ──
    "test_title":           {"ru": "🔧 **Диагностика**",             "en": "🔧 **Diagnostics**"},
    "test_ping":            {"ru": "📡 Пинг до сервера",             "en": "📡 Ping to server"},
    "test_port_vless":      {"ru": "🔌 Порт VLESS ({})",             "en": "🔌 VLESS port ({})"},
    "test_port_wg":         {"ru": "🔌 Порт WG ({})",                "en": "🔌 WG port ({})"},
    "test_xray_status":     {"ru": "🔄 Xray сервис",                 "en": "🔄 Xray service"},
    "test_sub_status":      {"ru": "🔑 Подписка",                    "en": "🔑 Subscription"},
    "test_server_load":     {"ru": "💻 Нагрузка сервера",            "en": "💻 Server load"},
    "test_cpu":             {"ru": "CPU",                           "en": "CPU"},
    "test_mem":             {"ru": "Память",                         "en": "Memory"},
    "test_disk":            {"ru": "Диск",                           "en": "Disk"},
    "test_ok":              {"ru": "✅",                             "en": "✅"},
    "test_fail":            {"ru": "❌",                             "en": "❌"},
    "test_no_sub":          {"ru": "Нет активной подписки",          "en": "No active subscription"},
    "test_active_until":    {"ru": "Активна до {}",                  "en": "Active until {}"},
    "test_running":         {"ru": "🔍 Проверяю...",                 "en": "🔍 Checking..."},

    # ── Backup system ──
    "backup_created":       {"ru": "✅ Бэкап создан: {} ({} KB)",    "en": "✅ Backup created: {} ({} KB)"},
    "backup_restored":      {"ru": "✅ Бэкап восстановлен из: {}",   "en": "✅ Backup restored from: {}"},
    "backup_error":         {"ru": "❌ Ошибка бэкапа: {}",           "en": "❌ Backup error: {}"},
    "backup_not_found":     {"ru": "❌ Бэкапы не найдены",          "en": "❌ No backups found"},
    "backup_list":          {"ru": "📦 **Бэкапы:**",                 "en": "📦 **Backups:**"},
    "backup_restore_usage": {"ru": "Использование: /admin restore <filename>", "en": "Usage: /admin restore <filename>"},
    "backup_restored_ok":   {"ru": "✅ Бэкап восстановлен. Перезапускаю Xray...\\nРезультат: {}", "en": "✅ Backup restored. Restarting Xray...\\nResult: {}"},

    # ── Enhanced admin stats ──
    "admin_revenue_7d":     {"ru": "💵 Выручка 7д:",                 "en": "💵 Revenue 7d:"},
    "admin_revenue_30d":    {"ru": "💵 Выручка 30д:",                "en": "💵 Revenue 30d:"},
    "admin_new_users_7d":   {"ru": "🆕 Новых за 7д:",               "en": "🆕 New users 7d:"},
    "admin_new_users_30d":  {"ru": "🆕 Новых за 30д:",              "en": "🆕 New users 30d:"},
    "admin_conversion":     {"ru": "🔄 Конверсия (триал→платный):",  "en": "🔄 Conversion (trial→paid):"},
    "admin_conversion_pct": {"ru": "{}%",                           "en": "{}%"},
    "admin_popular_plan":   {"ru": "⭐ Популярный план:",            "en": "⭐ Popular plan:"},
    "admin_sparkline":      {"ru": "📈 Доход по дням (7д):",        "en": "📈 Daily revenue (7d):"},
    "admin_sparkline_ton":  {"ru": "{} TON",                        "en": "{} TON"},
}

LANG_DEFAULT = os.environ.get("LANG_DEFAULT", "ru").strip()


def get_lang(conn: sqlite3.Connection, tg_id: int) -> str:
    """Read user's language preference from DB. Falls back to default."""
    row = conn.execute("SELECT lang FROM users WHERE tg_id=?", (tg_id,)).fetchone()
    if row and row["lang"]:
        return row["lang"]
    return LANG_DEFAULT


def set_lang(conn: sqlite3.Connection, tg_id: int, lang: str):
    """Store user's language preference."""
    conn.execute(
        "INSERT INTO users (tg_id, created_at, lang) VALUES (?,?,?) "
        "ON CONFLICT(tg_id) DO UPDATE SET lang=excluded.lang",
        (tg_id, int(time.time()), lang),
    )
    conn.commit()


def t(key: str, lang: str, *args) -> str:
    """Translate a key for the given language, formatting positional args."""
    entry = T.get(key, {})
    text = entry.get(lang) or entry.get("en") or entry.get("ru") or key
    if args:
        return text.format(*args)
    return text


CRYPTOBOT_BASE = "https://pay.crypt.bot/api"

# Auto-check settings (seconds)
AUTOCHECK_POLL_INTERVAL = int(os.environ.get("AUTOCHECK_POLL_INTERVAL", "12"))
AUTOCHECK_TIMEOUT = int(os.environ.get("AUTOCHECK_TIMEOUT", "180"))

# Track running auto-check tasks per user to avoid spawning duplicates
AUTO_CHECK_TASKS: dict[int, asyncio.Task] = {}

# ── Improvement #4: TON rate caching ──
RATE_CACHE_TTL = int(os.environ.get("RATE_CACHE_TTL", "300"))  # 5 min default
TON_RATE_FALLBACK_SOURCES = [
    "https://api.coingecko.com/api/v3/simple/price?ids=the-open-network&vs_currencies=usd",
    "https://api.binance.com/api/v3/ticker/price?symbol=TONUSDT",
]
# In-memory rate cache (survives between calls, resets on restart)
_rate_cache: dict = {"ton_usd": 0.0, "updated_at": 0}

# ── Improvement #3: Expiry notifications ──
NOTIFY_BEFORE_HOURS = [
    int(h) for h in os.environ.get("NOTIFY_BEFORE_HOURS", "72,24").split(",")
    if h.strip().lstrip("-").isdigit()
]
NOTIFY_INTERVAL_SEC = int(os.environ.get("NOTIFY_INTERVAL_SEC", "3600"))  # check every 1h

# ── Improvement #2: Xray config management ──
# Note: xray does not support SIGHUP for config reload (SIGHUP kills the process).
# For zero-downtime client addition, future enhancement: enable xray gRPC API.
# Current approach: validated restart with backup/rollback — downtime ~1-2s, VLESS clients auto-reconnect.
XRAY_RELOAD_METHOD = os.environ.get("XRAY_RELOAD_METHOD", "restart")  # "restart" (default, safe)


def kb_main(lang: str = "ru") -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text=t("btn_trial", lang), callback_data="trial")],
            [
                InlineKeyboardButton(text=t("btn_buy_30", lang), callback_data="buy_30"),
                InlineKeyboardButton(text=t("btn_buy_90", lang), callback_data="buy_90"),
            ],
            [InlineKeyboardButton(text=t("btn_buy_180", lang), callback_data="buy_180")],
            [InlineKeyboardButton(text=t("btn_promo", lang), callback_data="promo")],
            [InlineKeyboardButton(text=t("btn_wg_access", lang), callback_data="wg_access")],
            [InlineKeyboardButton(text=t("btn_xkeen", lang), callback_data="xkeen")],
            [InlineKeyboardButton(text=t("btn_proxy", lang), callback_data="proxy_buy")],
            [InlineKeyboardButton(text=t("btn_referral", lang), callback_data="referral")],
            [InlineKeyboardButton(text=t("btn_my_access", lang), callback_data="my_access")],
            [InlineKeyboardButton(text=t("btn_help", lang), callback_data="help")],
            [InlineKeyboardButton(text=t("btn_support", lang), callback_data="support")],
            [InlineKeyboardButton(text=t("btn_lang", lang), callback_data="lang")],
        ]
    )


async def run_async(cmd, timeout=10):
    """Run subprocess without blocking asyncio event loop."""
    proc = await asyncio.create_subprocess_exec(
        *cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
    )
    try:
        stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=timeout)
        return stdout.decode(), stderr.decode(), proc.returncode
    except asyncio.TimeoutError:
        proc.kill()
        raise


def db() -> sqlite3.Connection:
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=NORMAL")
    conn.execute("PRAGMA cache_size=-8000")
    conn.execute("PRAGMA busy_timeout=5000")
    return conn


def init_db():
    with db() as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS users (
              tg_id INTEGER PRIMARY KEY,
              created_at INTEGER NOT NULL,
              main_chat_id INTEGER,
              main_message_id INTEGER,
              trial_used INTEGER NOT NULL DEFAULT 0,
              referrer_tg_id INTEGER
            );
            """
        )
        # lightweight migration for existing DBs
        cols = {r[1] for r in conn.execute("PRAGMA table_info(users)").fetchall()}
        if "main_chat_id" not in cols:
            conn.execute("ALTER TABLE users ADD COLUMN main_chat_id INTEGER")
        if "main_message_id" not in cols:
            conn.execute("ALTER TABLE users ADD COLUMN main_message_id INTEGER")
        if "trial_used" not in cols:
            conn.execute("ALTER TABLE users ADD COLUMN trial_used INTEGER NOT NULL DEFAULT 0")
        if "referrer_tg_id" not in cols:
            conn.execute("ALTER TABLE users ADD COLUMN referrer_tg_id INTEGER")
        if "lang" not in cols:
            conn.execute("ALTER TABLE users ADD COLUMN lang TEXT")

        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS invoices (
              id INTEGER PRIMARY KEY AUTOINCREMENT,
              tg_id INTEGER NOT NULL,
              invoice_id TEXT NOT NULL,
              asset TEXT NOT NULL,
              amount REAL NOT NULL,
              status TEXT NOT NULL,
              created_at INTEGER NOT NULL,
              paid_at INTEGER,
              meta TEXT,
              fulfilled_at INTEGER,
              UNIQUE(invoice_id)
            );
            """
        )
        cols2 = {r[1] for r in conn.execute("PRAGMA table_info(invoices)").fetchall()}
        if "meta" not in cols2:
            conn.execute("ALTER TABLE invoices ADD COLUMN meta TEXT")
        if "fulfilled_at" not in cols2:
            conn.execute("ALTER TABLE invoices ADD COLUMN fulfilled_at INTEGER")

        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS subscriptions (
              id INTEGER PRIMARY KEY AUTOINCREMENT,
              tg_id INTEGER NOT NULL,
              uuid TEXT NOT NULL,
              created_at INTEGER NOT NULL,
              expires_at INTEGER NOT NULL,
              active INTEGER NOT NULL,
              wg_ip TEXT,
              wg_privkey TEXT,
              wg_pubkey TEXT
            );
            """
        )
        # Migration: add WG columns if missing
        cols = {r[1] for r in conn.execute("PRAGMA table_info(subscriptions)").fetchall()}
        if "wg_ip" not in cols:
            conn.execute("ALTER TABLE subscriptions ADD COLUMN wg_ip TEXT")
        if "wg_privkey" not in cols:
            conn.execute("ALTER TABLE subscriptions ADD COLUMN wg_privkey TEXT")
        if "wg_pubkey" not in cols:
            conn.execute("ALTER TABLE subscriptions ADD COLUMN wg_pubkey TEXT")
        # Migration: sub_type (proxy support)
        if "sub_type" not in cols:
            conn.execute("ALTER TABLE subscriptions ADD COLUMN sub_type TEXT")
            log.info("Migration: added sub_type column to subscriptions")

        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS promo_codes (
              code TEXT PRIMARY KEY,
              kind TEXT NOT NULL,             -- percent|usdt|days
              value REAL NOT NULL,
              max_uses INTEGER,
              used_count INTEGER NOT NULL DEFAULT 0,
              expires_at INTEGER,
              created_at INTEGER NOT NULL
            );
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS promo_redemptions (
              id INTEGER PRIMARY KEY AUTOINCREMENT,
              tg_id INTEGER NOT NULL,
              code TEXT NOT NULL,
              redeemed_at INTEGER NOT NULL,
              UNIQUE(tg_id, code)
            );
            """
        )

        # ── Improvement #4: rate cache table ──
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS rate_cache (
              source TEXT PRIMARY KEY,
              ton_usd REAL NOT NULL,
              updated_at INTEGER NOT NULL
            );
            """
        )

        # ── Improvement #3: expiry notification tracking ──
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS expiry_notifications (
              id INTEGER PRIMARY KEY AUTOINCREMENT,
              subscription_id INTEGER NOT NULL,
              tg_id INTEGER NOT NULL,
              hours_before INTEGER NOT NULL,
              sent_at INTEGER NOT NULL,
              UNIQUE(subscription_id, hours_before)
            );
            """
        )

        # Performance indexes
        conn.execute("CREATE INDEX IF NOT EXISTS idx_subs_active_tg ON subscriptions(tg_id, active)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_subs_expires ON subscriptions(expires_at) WHERE active=1")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_inv_tg_status ON invoices(tg_id, status)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_inv_invoice_id ON invoices(invoice_id)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_users_referrer ON users(referrer_tg_id)")

        conn.commit()


async def cryptobot_request(method: str, payload: dict | None = None) -> dict:
    if not CRYPTOBOT_TOKEN:
        raise RuntimeError("CRYPTOBOT_TOKEN is not set")

    headers = {"Crypto-Pay-API-Token": CRYPTOBOT_TOKEN}
    async with httpx.AsyncClient(timeout=30) as client:
        r = await client.post(f"{CRYPTOBOT_BASE}/{method}", headers=headers, json=payload or {})
        r.raise_for_status()
        data = r.json()
        if not data.get("ok"):
            raise RuntimeError(f"CryptoBot API error: {data}")
        return data["result"]


# ── Improvement #4: Cached TON rate with multi-source fallback ──

async def _fetch_ton_rate_from_source(url: str, source_name: str) -> float | None:
    """Try to fetch TON/USD rate from a single source. Returns rate or None."""
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            r = await client.get(url)
            r.raise_for_status()
            j = r.json()
            if "coingecko" in url:
                return float(j["the-open-network"]["usd"])
            if "binance" in url:
                return float(j["price"])
            return None
    except Exception as e:
        log.warning("Rate source %s failed: %s", source_name, e)
        return None


async def get_ton_rate() -> float:
    """Get TON/USD rate with layered caching: memory → DB → API with fallback."""
    now = int(time.time())

    # Layer 1: in-memory cache
    if _rate_cache["updated_at"] and (now - _rate_cache["updated_at"]) < RATE_CACHE_TTL:
        return _rate_cache["ton_usd"]

    # Layer 2: DB cache
    with db() as conn:
        row = conn.execute(
            "SELECT ton_usd, updated_at FROM rate_cache WHERE source='memory'"
        ).fetchone()
        if row and (now - int(row["updated_at"])) < RATE_CACHE_TTL:
            rate = float(row["ton_usd"])
            _rate_cache["ton_usd"] = rate
            _rate_cache["updated_at"] = int(row["updated_at"])
            return rate

    # Layer 3: fetch from API sources
    for url in TON_RATE_FALLBACK_SOURCES:
        source_name = "coingecko" if "coingecko" in url else "binance"
        rate = await _fetch_ton_rate_from_source(url, source_name)
        if rate and rate > 0:
            # Update both caches
            _rate_cache["ton_usd"] = rate
            _rate_cache["updated_at"] = now
            with db() as conn:
                conn.execute(
                    "INSERT OR REPLACE INTO rate_cache (source, ton_usd, updated_at) VALUES (?,?,?)",
                    ("memory", rate, now),
                )
                conn.commit()
            return rate

    # Layer 4: stale cache (last resort)
    if _rate_cache["ton_usd"] > 0:
        age_min = (now - _rate_cache["updated_at"]) // 60
        log.warning("All rate sources failed, using %d-minute-old cached rate", age_min)
        return _rate_cache["ton_usd"]

    with db() as conn:
        row = conn.execute("SELECT ton_usd FROM rate_cache WHERE source='memory'").fetchone()
        if row and float(row["ton_usd"]) > 0:
            log.warning("All rate sources failed, using DB-cached rate")
            return float(row["ton_usd"])

    raise RuntimeError("Cannot determine TON/USD rate — all sources offline and no cache")


async def get_ton_price_for_usdt(usdt_amount: float) -> float:
    ton_usd = await get_ton_rate()
    ton_amount = usdt_amount / ton_usd
    # safety floor
    return max(PRICE_TON_MIN, round(ton_amount, 3))


def latest_invoice(tg_id: int) -> sqlite3.Row | None:
    # Prefer unpaid/active invoice if present, otherwise latest.
    with db() as conn:
        row = conn.execute(
            "SELECT * FROM invoices WHERE tg_id=? AND status!='paid' ORDER BY id DESC LIMIT 1",
            (tg_id,),
        ).fetchone()
        if row:
            return row
        row = conn.execute(
            "SELECT * FROM invoices WHERE tg_id=? ORDER BY id DESC LIMIT 1",
            (tg_id,),
        ).fetchone()
        return row


def latest_sub(tg_id: int) -> sqlite3.Row | None:
    with db() as conn:
        row = conn.execute(
            "SELECT * FROM subscriptions WHERE tg_id=? AND (sub_type IS NULL OR sub_type='vless') ORDER BY id DESC LIMIT 1", (tg_id,)
        ).fetchone()
        return row


def latest_sub_type(tg_id: int, sub_type: str) -> sqlite3.Row | None:
    with db() as conn:
        row = conn.execute(
            "SELECT * FROM subscriptions WHERE tg_id=? AND sub_type=? AND active=1 ORDER BY id DESC LIMIT 1", (tg_id, sub_type)
        ).fetchone()
        return row


def create_or_extend_sub(tg_id: int, new_uuid: str, days: int) -> sqlite3.Row:
    now = int(time.time())
    delta = days * 86400

    with db() as conn:
        active = conn.execute(
            "SELECT * FROM subscriptions WHERE tg_id=? AND active=1 ORDER BY id DESC LIMIT 1",
            (tg_id,),
        ).fetchone()

        # extend existing subscription without rotating UUID
        if active and active["expires_at"] > now:
            conn.execute(
                "UPDATE subscriptions SET expires_at=? WHERE id=?",
                (int(active["expires_at"]) + delta, int(active["id"])),
            )
            conn.commit()
            return latest_sub(tg_id)

        # else create new
        expires = now + delta
        conn.execute("UPDATE subscriptions SET active=0 WHERE tg_id=?", (tg_id,))
        conn.execute(
            "INSERT INTO subscriptions (tg_id, uuid, created_at, expires_at, active) VALUES (?,?,?,?,1)",
            (tg_id, new_uuid, now, expires),
        )
        conn.commit()

    return latest_sub(tg_id)


def create_or_extend_sub_trial(tg_id: int, new_uuid: str, minutes: int) -> sqlite3.Row:
    """Create a short trial subscription (does NOT extend paid ones)."""
    now = int(time.time())
    expires = now + int(minutes) * 60
    with db() as conn:
        # do not touch existing paid active sub; trial just becomes latest record but marked active.
        conn.execute(
            "INSERT INTO subscriptions (tg_id, uuid, created_at, expires_at, active) VALUES (?,?,?,?,1)",
            (tg_id, new_uuid, now, expires),
        )
        conn.commit()
    return latest_sub(tg_id)


def set_trial_used(tg_id: int):
    with db() as conn:
        conn.execute("UPDATE users SET trial_used=trial_used+1 WHERE tg_id=?", (tg_id,))
        conn.commit()


def get_trial_used(tg_id: int) -> int:
    with db() as conn:
        row = conn.execute("SELECT trial_used FROM users WHERE tg_id=?", (tg_id,)).fetchone()
        return int(row["trial_used"]) if row and row["trial_used"] is not None else 0


def normalize_promo(code: str) -> str:
    return (code or "").strip().upper()


def promo_get(code: str) -> sqlite3.Row | None:
    code = normalize_promo(code)
    with db() as conn:
        return conn.execute("SELECT * FROM promo_codes WHERE code=?", (code,)).fetchone()


def promo_can_redeem(tg_id: int, code: str) -> tuple[bool, str]:
    code = normalize_promo(code)
    row = promo_get(code)
    if not row:
        return False, "promo_not_found"
    now = int(time.time())
    if row["expires_at"] and int(row["expires_at"]) < now:
        return False, "promo_expired"
    if row["max_uses"] is not None and int(row["used_count"]) >= int(row["max_uses"]):
        return False, "promo_limit_reached"
    with db() as conn:
        used = conn.execute(
            "SELECT 1 FROM promo_redemptions WHERE tg_id=? AND code=?",
            (tg_id, code),
        ).fetchone()
    if used:
        return False, "promo_already_used"
    return True, "ok"


def promo_redeem(tg_id: int, code: str):
    """Атомарный redeem промокода. Возвращает True если успешно."""
    code = normalize_promo(code)
    now = int(time.time())
    with db() as conn:
        # Check promo exists and is active
        promo = conn.execute(
            "SELECT max_uses, used_count, valid_from, valid_until FROM promo_codes WHERE code=?",
            (code,)
        ).fetchone()
        if not promo:
            return False
        if promo["valid_from"] and now < int(promo["valid_from"]):
            return False
        if promo["valid_until"] and now > int(promo["valid_until"]):
            return False
        
        # Atomic: increment only if under limit
        cur = conn.execute(
            "UPDATE promo_codes SET used_count = used_count + 1 WHERE code=? AND used_count < max_uses",
            (code,)
        )
        if cur.rowcount == 0:
            return False  # limit reached or race lost
        
        # Check user hasn't already used this code
        try:
            conn.execute(
                "INSERT INTO promo_redemptions (tg_id, code, redeemed_at) VALUES (?,?,?)",
                (tg_id, code, now),
            )
        except sqlite3.IntegrityError:
            # Already redeemed — rollback the used_count increment
            conn.rollback()
            return False
        
        conn.commit()
        return True


def promo_apply_price(usdt_price: float, code: str) -> tuple[float, int, str]:
    """Returns (new_price, bonus_days, description)."""
    row = promo_get(code)
    if not row:
        return usdt_price, 0, ""
    kind = str(row["kind"])
    val = float(row["value"])
    if kind == "percent":
        new_price = max(0.01, usdt_price * (1.0 - val / 100.0))
        return new_price, 0, f"-{val:.0f}%"
    if kind == "usdt":
        new_price = max(0.01, usdt_price - val)
        return new_price, 0, f"-{val:.2f} USDT"
    if kind == "days":
        return usdt_price, int(val), f"+{int(val)} дней"
    return usdt_price, 0, ""


def create_client_id(email: str) -> str:
    # For seller-managed core, client identifier is just UUID.
    return str(uuid.uuid4())


def list_active_uuids(now: int | None = None) -> list[str]:
    now = now or int(time.time())
    with db() as conn:
        rows = conn.execute(
            "SELECT uuid FROM subscriptions WHERE active=1 AND expires_at>?",
            (now,),
        ).fetchall()
        return [r["uuid"] for r in rows]


def reconcile_subscriptions(now: int | None = None) -> int:
    """Mark expired subscriptions inactive. Returns number of changed rows."""
    now = now or int(time.time())
    with db() as conn:
        cur = conn.execute(
            "UPDATE subscriptions SET active=0 WHERE active=1 AND expires_at<=?",
            (now,),
        )
        conn.commit()
        return cur.rowcount


def write_xray_config_from_template(active_uuids: list[str]):
    """Generate XRAY config from template and write atomically with backup.

    Note: This function only writes the file. Validation + reload is handled elsewhere.
    """
    # De-dupe UUIDs just in case
    active_uuids = sorted({str(u).strip() for u in active_uuids if str(u).strip()})

    with open("/opt/vpn-core/conf/config.template.json", "r", encoding="utf-8") as f:
        cfg = json.load(f)

    # email must be unique per client, otherwise xray fails with "User sub already exists."
    clients = [{"id": u, "email": f"sub-{u}"} for u in active_uuids]
    if not clients:
        # keep config valid: one dummy client
        clients = [{"id": "00000000-0000-0000-0000-000000000000", "email": "disabled"}]

    cfg["inbounds"][0]["settings"]["clients"] = clients

    tmp_path = XRAY_CONFIG_PATH + ".tmp"
    with open(tmp_path, "w", encoding="utf-8") as f:
        json.dump(cfg, f, ensure_ascii=False, indent=2)

    os.replace(tmp_path, XRAY_CONFIG_PATH)


def test_xray_config(config_path: str) -> tuple[bool, str]:
    """Validate xray config before reload. Returns (ok, message)."""
    try:
        r = subprocess.run(
            ["/opt/vpn-core/bin/xray", "run", "-test", "-config", config_path],
            capture_output=True,
            text=True,
            timeout=10,
        )
        if r.returncode == 0:
            return True, "ok"
        msg = (r.stderr or r.stdout or "").strip()
        return False, msg[-800:]
    except Exception as e:
        return False, f"{type(e).__name__}: {e}"


def _rollback_xray_config():
    """Restore config from backup if available."""
    bak_path = XRAY_CONFIG_PATH + ".bak"
    if os.path.exists(bak_path):
        os.replace(bak_path, XRAY_CONFIG_PATH)
        log.warning("Rolled back xray config from backup")
        return True
    return False


def _backup_xray_config():
    """Create a backup of the current xray config before modifying."""
    if os.path.exists(XRAY_CONFIG_PATH):
        import shutil
        shutil.copy2(XRAY_CONFIG_PATH, XRAY_CONFIG_PATH + ".bak")


def rebuild_and_reload_xray() -> tuple[bool, str]:
    """Rebuild config from DB, validate, then reload (SIGHUP) service.

    Improvement #2: Uses systemctl reload instead of restart — no connection drops.
    Improvement #5: Atomic with backup/rollback on validation failure.

    Returns (ok, message).
    """
    reconcile_subscriptions()
    active_uuids = list_active_uuids()

    _backup_xray_config()
    write_xray_config_from_template(active_uuids)

    ok, msg = test_xray_config(XRAY_CONFIG_PATH)
    if not ok:
        log.error("xray config test failed: %s — rolling back", msg)
        _rollback_xray_config()
        # Re-test the rolled-back config
        ok2, msg2 = test_xray_config(XRAY_CONFIG_PATH)
        if not ok2:
            log.critical("Rolled-back config also fails test! %s", msg2)
        return False, f"xray config test failed: {msg}"

    try:
        subprocess.run(["sudo", "systemctl", "restart", XRAY_SERVICE], check=True, timeout=20)
    except Exception as e:
        return False, f"reload failed: {type(e).__name__}: {e}"

    return True, "reloaded"


def rebuild_and_restart_xray() -> tuple[bool, str]:
    """Legacy wrapper — delegates to rebuild_and_reload_xray."""
    return rebuild_and_reload_xray()



def get_next_wg_ip() -> str:
    """Allocate next available WireGuard client IP."""
    with db() as conn:
        rows = conn.execute(
            "SELECT wg_ip FROM subscriptions WHERE active=1 AND wg_ip IS NOT NULL ORDER BY wg_ip"
        ).fetchall()
    used = {r["wg_ip"] for r in rows}
    for i in range(2, 254):
        ip = f"{WG_SUBNET}.{i}"
        if ip not in used:
            return ip
    return f"{WG_SUBNET}.99"  # fallback


def add_wg_peer(client_privkey: str, client_ip: str) -> tuple[bool, str]:
    """Add WireGuard peer and reload config."""
    try:
        pubkey = subprocess.run(
            ["wg", "pubkey"], input=client_privkey, capture_output=True, text=True, timeout=5
        ).stdout.strip()
        with open(WG_CONFIG_PATH, "a") as f:
            f.write(f"\n[Peer]\nPublicKey = {pubkey}\nAllowedIPs = {client_ip}/32\n")
        subprocess.run(["sudo", "wg", "addconf", "wg0"], input=f"public_key={pubkey}\nallowed_ip={client_ip}/32\n",
                       capture_output=True, text=True, timeout=10, check=True)
        return True, pubkey
    except Exception as e:
        return False, str(e)


def remove_wg_peer(pubkey: str) -> bool:
    """Remove WireGuard peer."""
    try:
        subprocess.run(["sudo", "wg", "set", "wg0", "peer", pubkey, "remove"], capture_output=True, timeout=5, check=True)
        # Also remove from config file
        with open(WG_CONFIG_PATH) as f:
            lines = f.readlines()
        with open(WG_CONFIG_PATH, "w") as f:
            skip = False
            for line in lines:
                if f"PublicKey = {pubkey}" in line:
                    skip = True
                    continue
                if skip and line.startswith("["):
                    skip = False
                if not skip:
                    f.write(line)
        return True
    except Exception:
        return False


def _get_server_pubkey() -> str:
    """Resolve WireGuard server public key."""
    if WG_SERVER_PUBKEY:
        return WG_SERVER_PUBKEY
    try:
        priv = subprocess.run(["cat", WG_SERVER_PRIVKEY_PATH], capture_output=True, text=True, timeout=5)
        return subprocess.run(["wg", "pubkey"], input=priv.stdout, capture_output=True, text=True, timeout=5).stdout.strip()
    except Exception:
        return "UNKNOWN"


def build_wireguard_config(client_privkey: str, client_ip: str, client_pubkey: str = "", amnezia: bool = False) -> str:
    """Build WireGuard or AmneziaWG client config."""
    server_pub = _get_server_pubkey()
    cfg = f"""[Interface]
PrivateKey = {client_privkey}
Address = {client_ip}/32
DNS = 1.1.1.1, 8.8.8.8
"""
    if amnezia:
        cfg += f"""Jc = {WG_AMNEZIA_JC}
Jmin = {WG_AMNEZIA_JMIN}
Jmax = {WG_AMNEZIA_JMAX}
S1 = {WG_AMNEZIA_S1}
S2 = {WG_AMNEZIA_S2}
H1 = {WG_AMNEZIA_H1}
H2 = {WG_AMNEZIA_H2}
H3 = {WG_AMNEZIA_H3}
H4 = {WG_AMNEZIA_H4}
"""
    cfg += f"""
[Peer]
PublicKey = {server_pub}
AllowedIPs = 0.0.0.0/0
Endpoint = {SERVER_IP}:{WG_PORT}
PersistentKeepalive = 25
"""
    return cfg


def build_vless_link(client_uuid: str) -> str:
    import urllib.parse

    params = {
        "type": "tcp",
        "security": "reality",
        "encryption": "none",
        "pbk": VLESS_PBK,
        "sid": VLESS_SID,
        "sni": VLESS_SNI,
        "fp": VLESS_FINGERPRINT,
        "spx": "/",
        "allowInsecure": "1",
    }
    qs = urllib.parse.urlencode(params)
    name = urllib.parse.quote("vpn")
    return f"vless://{client_uuid}@{SERVER_IP}:{VLESS_PORT}?{qs}#{name}"


def build_vless_backup_link(client_uuid: str) -> str:
    """Build vless:// link for the backup Reality port (Level 2 anti-censorship)."""
    import urllib.parse

    params = {
        "type": "tcp",
        "security": "reality",
        "encryption": "none",
        "pbk": VLESS_BACKUP_PBK,
        "sid": VLESS_BACKUP_SID,
        "sni": VLESS_BACKUP_SNI,
        "fp": VLESS_FINGERPRINT,
        "spx": "/",
        "allowInsecure": "1",
    }
    qs = urllib.parse.urlencode(params)
    name = urllib.parse.quote(f"vpn-backup ({VLESS_BACKUP_SNI})")
    return f"vless://{client_uuid}@{SERVER_IP}:{VLESS_BACKUP_PORT}?{qs}#{name}"


def build_xkeen_config(client_uuid: str) -> str:
    """Generate XKeen (Keenetic router) VLESS+REALITY config as JSON import string.

    XKeen uses an Xray-compatible JSON outbound config. This produces a
    minimal outbound-only config that the Keenetic router can import directly.
    """
    cfg = {
        "outbounds": [
            {
                "protocol": "vless",
                "settings": {
                    "vnext": [
                        {
                            "address": SERVER_IP,
                            "port": VLESS_PORT,
                            "users": [
                                {
                                    "id": client_uuid,
                                    "encryption": "none"
                                }
                            ],
                        }
                    ]
                },
                "streamSettings": {
                    "network": "tcp",
                    "security": "reality",
                    "realitySettings": {
                        "serverName": VLESS_SNI,
                        "fingerprint": VLESS_FINGERPRINT,
                        "publicKey": VLESS_PBK,
                        "shortId": VLESS_SID,
                    },
                },
                "tag": "proxy",
            }
        ]
    }
    return json.dumps(cfg, ensure_ascii=False, indent=2)


def get_traffic_stats(lang: str = "ru") -> str:
    """Get traffic stats via vnstat if available."""
    try:
        r = subprocess.run(["vnstat", "-i", "ens3", "-m", "--oneline"], capture_output=True, text=True, timeout=5)
        if r.returncode != 0 or not r.stdout.strip():
            return ""
        # Parse last 2 months: "1;eth0;2026-05-01;12.34;56.78;69.12;..."
        lines = r.stdout.strip().split("\n")
        months = []
        for line in lines[-2:]:
            parts = line.split(";")
            if len(parts) >= 5:
                months.append(f"{parts[2][:7]}: ↓{parts[3]} ↑{parts[4]}")
        if months:
            return t("traffic_header", lang) + "\n" + "\n".join(months)
    except Exception as e:
        log.warning(f'ex: {e}')
    return ""


def get_vpn_watch_status() -> dict:
    """Read live VPN status from vpn-watch.py JSON output."""
    try:
        with open("/opt/vpn-core/conf/vpn-watch-status.json") as f:
            data = json.load(f)
        log.info("vpn-watch-status: traffic_active=%s, rx=%s, tx=%s", data.get("traffic_active"), data.get("rx_fmt"), data.get("tx_fmt"))
        return data
    except Exception as e:
        log.warning("vpn-watch-status read failed: %s", e)
        return {}


def format_vpn_watch_status(status: dict, lang: str = "ru") -> str:
    """Format VPN watch status for Telegram."""
    if not status:
        return "📡 Нет данных (запусти vpn-watch.py)"

    ts = status.get("ts", 0)
    ago = int(time.time() - ts) if ts else 999
    ago_str = f"{ago}с назад" if ago < 120 else f"{ago // 60}м назад"

    service = status.get("service", "?")
    port = status.get("port_status", "?")
    active = status.get("traffic_active", False)
    rx = status.get("rx_fmt", "?")
    tx = status.get("tx_fmt", "?")
    errors = status.get("xray_errors", 0)

    s_icon = "✅" if service == "active" else "❌"
    p_icon = "✅" if port == "open" else "❌"
    t_icon = "🟢" if active else "🔴"

    lines = [
        "📡 VPN Traffic Live",
        f"🔄 Сервис: {s_icon} {service}",
        f"🔌 Порт 4443: {p_icon} {port}",
        f"📊 Трафик: {t_icon} {'идёт' if active else 'НЕТ'} ({rx}↓ {tx}↑)",
        f"⚠️ Ошибок в логе: {errors}",
        f"🕐 Обновлено: {ago_str}",
    ]
    return "\n".join(lines)


def qr_png_bytes(data: str) -> bytes:
    img = qrcode.make(data)
    import io

    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


async def provision_access(bot: Bot, chat_id: int, tg_id: int, days: int = SUB_DAYS_30, bonus_days: int = 0):
    """Grant/extend subscription and push link+QR. Serialized with PROVISION_LOCK."""
    lang = "ru"
    try:
        _conn = db()
        lang = get_lang(_conn, tg_id)
        _conn.close()
    except Exception as e:
        log.warning(f'ex: {e}')

    async with PROVISION_LOCK:
        # Extend if active; otherwise create new UUID
        current = latest_sub(tg_id)
        if current and current["active"] and current["expires_at"] > int(time.time()):
            client_uuid = current["uuid"]
        else:
            client_uuid = create_client_id(email=f"tg{tg_id}")

        total_days = int(days) + int(bonus_days)
        # Referral bonus: if this user has a referrer, give bonus days
        referrer_id = None
        with db() as conn:
            row = conn.execute("SELECT referrer_tg_id FROM users WHERE tg_id=?", (tg_id,)).fetchone()
            if row and row["referrer_tg_id"]:
                referrer_id = row["referrer_tg_id"]
        if referrer_id:
            # Prevent self-referral
            if int(referrer_id) == int(tg_id):
                referrer_id = None
        if referrer_id:
            try:
                # Give bonus to referrer (one-time per referral)
                import json as _json
                with db() as conn:
                    already = conn.execute(
                        "SELECT 1 FROM invoices WHERE tg_id=? AND status='paid' AND paid_at IS NOT NULL",
                        (tg_id,)
                    ).fetchone()
                if not already:
                    # First payment — grant referral bonus
                    ref_sub = latest_sub(referrer_id)
                    if ref_sub and ref_sub["active"] and ref_sub["expires_at"] > int(time.time()):
                        _conn_ref = db()
                        ref_lang = get_lang(_conn_ref, referrer_id)
                        _conn_ref.execute(
                            "UPDATE subscriptions SET expires_at=expires_at+? WHERE id=?",
                            (REFERRAL_BONUS_DAYS * 86400, ref_sub["id"]),
                        )
                        _conn_ref.commit()
                        _conn_ref.close()
                        log.info("Referral bonus: +%d days for tg_id=%s (referred by %s)", REFERRAL_BONUS_DAYS, referrer_id, tg_id)
                        await bot.send_message(
                            referrer_id,
                            t("ref_bonus_msg", ref_lang, REFERRAL_BONUS_DAYS,
                              time.strftime('%Y-%m-%d %H:%M', time.localtime(ref_sub['expires_at'] + REFERRAL_BONUS_DAYS * 86400))),
                        )
            except Exception as e:
                log.warning("Referral bonus failed for tg_id=%s: %s", tg_id, e)
        sub = create_or_extend_sub(tg_id, client_uuid, total_days)

        ok, msg = rebuild_and_restart_xray()
        if not ok:
            log.error("xray rebuild/restart failed: %s", msg)
            await bot.send_message(chat_id, f"❌ {t('support_xray_fail', lang)}\n{msg}")
            return  # ⚠️ Stop — don't send broken config to client

        # Refresh main screen first
        await upsert_main_message(bot, chat_id, tg_id)

        link = build_vless_link(sub["uuid"])
        png = qr_png_bytes(link)
        extra = f"\n{t('payment_bonus', lang, bonus_days)}" if bonus_days else ""
        await bot.send_message(
            chat_id,
            f"{t('payment_confirmed', lang, days)}{extra}\n"
            f"{t('payment_active_until', lang)} {time.strftime('%Y-%m-%d %H:%M', time.localtime(sub['expires_at']))}"
            f"\n\n{t('payment_reimport', lang)}",
        )
        await bot.send_message(chat_id, link)
        await bot.send_photo(chat_id, BufferedInputFile(png, filename="vpn.png"))


async def send_stars_invoice(bot: Bot, chat_id: int, tg_id: int, days: int, stars_amount: int, lang: str):
    """Send Telegram Stars invoice and handle pre_checkout + successful_payment."""
    try:
        title = t("stars_invoice_title", lang, days)
        description = t("stars_invoice_desc", lang, days)

        # payload carries tariff metadata for successful_payment handler
        import json
        payload = json.dumps({"days": days, "tg_id": tg_id, "stars_amount": stars_amount})

        await bot.send_invoice(
            chat_id=chat_id,
            title=title,
            description=description,
            payload=payload,
            provider_token="",  # Stars don't need provider token
            currency="XTR",
            prices=[{"label": f"VPN {days}d", "amount": stars_amount}],
            start_parameter=f"vpn_{days}d",
        )

        await bot.send_message(
            chat_id,
            t("stars_desc", lang),
            reply_markup=kb_main(lang),
        )
    except Exception as e:
        log.exception("send_stars_invoice failed")
        await bot.send_message(
            chat_id,
            t("stars_error", lang, str(e)),
            reply_markup=kb_main(lang),
        )


async def auto_check_invoice(bot: Bot, chat_id: int, tg_id: int, invoice_id: str):
    """Poll CryptoBot for invoice status and auto-provision on paid."""
    lang = "ru"
    try:
        _conn = db()
        lang = get_lang(_conn, tg_id)
        _conn.close()
    except Exception as e:
        log.warning(f'ex: {e}')

    started = time.time()
    try:
        while True:
            if time.time() - started > AUTOCHECK_TIMEOUT:
                await bot.send_message(chat_id, t("autocheck_timeout", lang), reply_markup=kb_main(lang))
                return

            res = await cryptobot_request("getInvoices", {"invoice_ids": [invoice_id]})
            if res.get("items"):
                item = res["items"][0]
                status = item.get("status")

                with db() as conn:
                    conn.execute("UPDATE invoices SET status=? WHERE invoice_id=?", (status, invoice_id))
                    if status == "paid":
                        conn.execute(
                            "UPDATE invoices SET paid_at=? WHERE invoice_id=? AND paid_at IS NULL",
                            (int(time.time()), invoice_id),
                        )
                    conn.commit()

                if status == "paid":
                    # Determine tariff from invoice meta (if any)
                    days = SUB_DAYS_30
                    bonus_days = 0
                    already = False
                    try:
                        with db() as conn:
                            row = conn.execute("SELECT meta, fulfilled_at FROM invoices WHERE invoice_id=?", (invoice_id,)).fetchone()
                        if row and row["fulfilled_at"]:
                            already = True
                        if row and row["meta"]:
                            import json
                            meta = json.loads(row["meta"])
                            days = int(meta.get("days") or days)
                            bonus_days = int(meta.get("bonus_days") or 0)
                    except Exception as e:
                        log.warning(f'ex: {e}')

                    if already:
                        return

                    # Check if proxy invoice
                    if meta.get("type") == "proxy":
                        now = int(time.time())
                        new_uuid = "proxy_" + str(tg_id)
                        with db() as conn:
                            conn.execute(
                                "INSERT INTO subscriptions (tg_id, uuid, active, expires_at, sub_type, created_at) VALUES (?,?,1,?,?,?)",
                                (tg_id, new_uuid, now + days*86400, 'proxy', now)
                            )
                            conn.commit()
                        expires_str = time.strftime('%Y-%m-%d %H:%M', time.localtime(now + days*86400))
                        await bot.send_message(chat_id, t("proxy_access", lang).format(
                            server=PROXY_SERVER, port=PROXY_PORT, secret=PROXY_SECRET, expires=expires_str))
                    else:
                        await provision_access(bot, chat_id, tg_id, days=days, bonus_days=bonus_days)
                    with db() as conn:
                        conn.execute(
                            "UPDATE invoices SET fulfilled_at=? WHERE invoice_id=? AND fulfilled_at IS NULL",
                            (int(time.time()), invoice_id),
                        )
                        conn.commit()
                    return

            await asyncio.sleep(AUTOCHECK_POLL_INTERVAL)
    except asyncio.CancelledError:
        raise
    except Exception as e:
        log.exception("auto_check_invoice failed invoice_id=%s", invoice_id)
        await bot.send_message(chat_id, f"{t('autocheck_error', lang)}\n{type(e).__name__}: {e}", reply_markup=kb_main(lang))


def format_main_screen(tg_id: int, lang: str = "ru") -> str:
    now = int(time.time())
    sub = latest_sub(tg_id)
    active_until = None
    if sub and sub["active"] and sub["expires_at"] > now:
        active_until = time.strftime('%Y-%m-%d %H:%M', time.localtime(sub['expires_at']))

    inv = latest_invoice(tg_id)
    inv_line = ""
    if inv and inv["status"] != "paid":
        inv_line = f"\n{t('main_last_invoice', lang)} {inv['status']}"

    if active_until:
        status = f"{t('main_status_active', lang)} {active_until}"
        cta = f"\n\n{t('main_renew_cta', lang)}"
    else:
        status = t('main_status_inactive', lang)
        cta = f"\n\n{t('main_buy_cta', lang)}"

    return (
        f"{t('main_title', lang)}\n"
        f"{t('main_subtitle', lang)}\n"
        f"{t('main_payment', lang)}\n\n"
        f"{status}"
        f"{inv_line}"
        f"\n\n{t('main_plans_header', lang)}\n"
        f"• 30 дней — ~{PRICE_USDT_30:.2f} USDT\n"
        f"• 90 дней — ~{PRICE_USDT_90:.2f} USDT\n"
        f"• 180 дней — ~{PRICE_USDT_180:.2f} USDT\n"
        f"{cta}"
    )


async def upsert_main_message(bot: Bot, chat_id: int, tg_id: int):
    """Ensure there is exactly one 'main screen' message with keyboard."""
    with db() as conn:
        lang = get_lang(conn, tg_id)
        row = conn.execute("SELECT main_message_id FROM users WHERE tg_id=?", (tg_id,)).fetchone()
        main_message_id = row["main_message_id"] if row else None

    text = format_main_screen(tg_id, lang)

    if main_message_id:
        try:
            await bot.edit_message_text(text, chat_id=chat_id, message_id=int(main_message_id), reply_markup=kb_main(lang))
            return
        except Exception:
            # message might be deleted/too old/not editable; fall back to sending a new one
            pass

    msg = await bot.send_message(chat_id, text, reply_markup=kb_main(lang))
    with db() as conn:
        conn.execute(
            "INSERT INTO users (tg_id, created_at, main_chat_id, main_message_id) VALUES (?,?,?,?) "
            "ON CONFLICT(tg_id) DO UPDATE SET main_chat_id=excluded.main_chat_id, main_message_id=excluded.main_message_id",
            (tg_id, int(time.time()), int(chat_id), int(msg.message_id)),
        )
        conn.commit()


async def clear_keyboard(bot: Bot, chat_id: int, message_id: int | None):
    """Try to remove inline keyboard from a message (best effort)."""
    if not message_id:
        return
    try:
        await bot.edit_message_reply_markup(chat_id=chat_id, message_id=int(message_id), reply_markup=None)
    except Exception as e:
        log.warning(f'ex: {e}')


async def cmd_admin(message: Message):
    """Admin commands: /admin stats|issue|revoke|broadcast"""
    tg_id = message.from_user.id
    _conn = db()
    lang = get_lang(_conn, tg_id)
    _conn.close()

    if tg_id not in ADMIN_IDS:
        await message.reply(t("admin_denied", lang))
        return

    parts = (message.text or "").split(maxsplit=2)
    subcmd = parts[1].lower() if len(parts) > 1 else ""

    if subcmd == "stats":
        now = int(time.time())
        day_ago = now - 86400
        week_ago = now - 7 * 86400
        month_ago = now - 30 * 86400
        with db() as conn:
            users = conn.execute("SELECT COUNT(*) FROM users").fetchone()[0]
            active = conn.execute(
                "SELECT COUNT(*) FROM subscriptions WHERE active=1 AND expires_at > ?", (now,)
            ).fetchone()[0]
            paid = conn.execute(
                "SELECT COUNT(*) FROM invoices WHERE status='paid' AND fulfilled_at IS NOT NULL"
            ).fetchone()[0]
            revenue = conn.execute(
                "SELECT SUM(amount) FROM invoices WHERE status='paid'"
            ).fetchone()[0] or 0
            # 7d / 30d stats
            revenue_7d = conn.execute(
                "SELECT SUM(amount) FROM invoices WHERE status='paid' AND paid_at > ?", (week_ago,)
            ).fetchone()[0] or 0
            revenue_30d = conn.execute(
                "SELECT SUM(amount) FROM invoices WHERE status='paid' AND paid_at > ?", (month_ago,)
            ).fetchone()[0] or 0
            new_users_7d = conn.execute(
                "SELECT COUNT(*) FROM users WHERE created_at > ?", (week_ago,)
            ).fetchone()[0]
            new_users_30d = conn.execute(
                "SELECT COUNT(*) FROM users WHERE created_at > ?", (month_ago,)
            ).fetchone()[0]
            # Conversion: trial_used > 0 AND has paid invoice
            trial_users = conn.execute(
                "SELECT COUNT(*) FROM users WHERE trial_used > 0"
            ).fetchone()[0]
            paid_trial = conn.execute(
                "SELECT COUNT(DISTINCT u.tg_id) FROM users u JOIN invoices i ON u.tg_id=i.tg_id WHERE u.trial_used > 0 AND i.status='paid' AND i.fulfilled_at IS NOT NULL"
            ).fetchone()[0]
            conv = f"{paid_trial / trial_users * 100:.0f}%" if trial_users > 0 else "N/A"
            # Popular plan
            plans = conn.execute(
                "SELECT meta FROM invoices WHERE status='paid' AND meta IS NOT NULL"
            ).fetchall()
            plan_counts = {"30": 0, "90": 0, "180": 0}
            for (meta_json,) in plans:
                try:
                    m = json.loads(meta_json)
                    days = str(m.get("days", "30"))
                    if days in plan_counts:
                        plan_counts[days] += 1
                except Exception as e:
                    log.warning(f'ex: {e}')
            popular = max(plan_counts, key=plan_counts.get)
            popular_name = {"30": "30 дн", "90": "90 дн", "180": "180 дн"}.get(popular, popular)
            # Daily revenue sparkline (last 7 days)
            sparkline_parts = []
            for d in range(6, -1, -1):
                day_start = now - (d + 1) * 86400
                day_end = now - d * 86400
                day_rev = conn.execute(
                    "SELECT COALESCE(SUM(amount), 0) FROM invoices WHERE status='paid' AND paid_at > ? AND paid_at <= ?",
                    (day_start, day_end)
                ).fetchone()[0] or 0
                sparkline_parts.append(str(round(day_rev, 1)))

        lines = [
            f"{t('admin_stats_title', lang)}\n",
            f"{t('admin_stats_users', lang)} {users}",
            f"{t('admin_stats_active', lang)} {active}",
            f"{t('admin_stats_paid', lang)} {paid}",
            f"{t('admin_stats_revenue', lang)} {revenue:.1f} TON",
            f"{t('admin_revenue_7d', lang)} {revenue_7d:.1f} TON",
            f"{t('admin_revenue_30d', lang)} {revenue_30d:.1f} TON",
            f"{t('admin_new_users_7d', lang)} {new_users_7d}",
            f"{t('admin_new_users_30d', lang)} {new_users_30d}",
            f"{t('admin_conversion', lang)} {conv}",
            f"{t('admin_popular_plan', lang)} {popular_name} ({plan_counts[popular]} оплат)",
            f"{t('admin_sparkline', lang)} {' · '.join(sparkline_parts)} TON",
            f"\n{t('admin_stats_traffic', lang)} {get_traffic_stats() or 'N/A'}",
        ]
        await message.reply("\n".join(lines))

    elif subcmd == "issue":
        if len(parts) < 3:
            await message.reply(t("admin_issue_usage", lang))
            return
        args = parts[2].split()
        if len(args) < 2:
            await message.reply(t("admin_issue_usage", lang))
            return
        try:
            target_tg = int(args[0])
            days = int(args[1])
        except ValueError:
            await message.reply(t("admin_issue_must_be_num", lang))
            return
        client_uuid = create_client_id(email=f"tg{target_tg}")
        sub = create_or_extend_sub(target_tg, client_uuid, days)
        ok, msg = rebuild_and_reload_xray()
        link = build_vless_link(sub["uuid"])
        expires = time.strftime('%Y-%m-%d %H:%M', time.localtime(sub['expires_at']))
        status_icon = '✅' if ok else '❌ ' + msg
        await message.reply(
            t("admin_issue_done", lang, target_tg, sub['uuid'], days, expires, status_icon) +
            f"\n\n`{link}`"
        )
        try:
            # Get target user's language
            _tc = db()
            target_lang = get_lang(_tc, target_tg)
            _tc.close()
            await message.bot.send_message(
                target_tg,
                t("admin_issue_user_msg", target_lang, days, expires),
            )
        except Exception as e:
            log.warning(f'ex: {e}')

    elif subcmd == "revoke":
        if len(parts) < 3:
            await message.reply(t("admin_revoke_usage", lang))
            return
        try:
            target_tg = int(parts[2].strip())
        except ValueError:
            await message.reply(t("admin_revoke_must_be_num", lang))
            return
        with db() as conn:
            conn.execute(
                "UPDATE subscriptions SET active=0 WHERE tg_id=? AND active=1",
                (target_tg,),
            )
            conn.commit()
        ok, msg = rebuild_and_reload_xray()
        status_icon = '✅' if ok else '❌ ' + msg
        await message.reply(t("admin_revoke_done", lang, target_tg, status_icon))

    elif subcmd == "broadcast":
        if len(parts) < 3:
            await message.reply(t("admin_broadcast_usage", lang))
            return
        text = parts[2]
        with db() as conn:
            users = conn.execute("SELECT tg_id FROM users").fetchall()
        sent = 0
        for u in users:
            try:
                await message.bot.send_message(u["tg_id"], f"📢 {text}")
                sent += 1
            except Exception as e:
                log.warning(f'ex: {e}')
        await message.reply(t("admin_broadcast_sent", lang, sent, len(users)))

    elif subcmd == "health":
        with db() as conn:
            active = conn.execute(
                "SELECT COUNT(*) FROM subscriptions WHERE active=1 AND expires_at > strftime('%s','now')"
            ).fetchone()[0]
        xray_status = (await asyncio.to_thread(subprocess.run, ["systemctl", "is-active", "vpn-core-xray"], capture_output=True, text=True)).stdout.strip()
        ok, test_msg = test_xray_config(XRAY_CONFIG_PATH)
        xray_icon = '✅' if xray_status == 'active' else '❌'
        t_status = get_vpn_watch_status()
        traffic_block = "\n\n" + format_vpn_watch_status(t_status, lang) if t_status else ""
        await message.reply(
            f"{t('admin_health_title', lang)}\n\n"
            f"{t('admin_health_bot', lang)}\n"
            f"vpn-core-xray: {xray_icon} {xray_status}\n"
            f"Xray config: {'✅ valid' if ok else '❌ ' + test_msg}\n"
            f"{t('admin_stats_active', lang)} {active}\n"
            f"{t('admin_health_memory', lang)} {get_mem_mb():.0f} MB"
            f"{traffic_block}"
        )

    elif subcmd == "traffic":
        status = get_vpn_watch_status()
        await message.reply(format_vpn_watch_status(status, lang))

    elif subcmd == "backup":
        ok, result = create_backup()
        if ok:
            fname = os.path.basename(result)
            size_kb = os.path.getsize(result) // 1024
            await message.reply(t("backup_created", lang).format(fname, size_kb))
        else:
            await message.reply(t("backup_error", lang).format(result))

    elif subcmd == "restore":
        if len(parts) < 3:
            # List backups
            files = list_backups()
            if not files:
                await message.reply(t("backup_not_found", lang))
            else:
                lines = [t("backup_list", lang)]
                for f in files[:10]:
                    fpath = os.path.join(BACKUP_DIR, f)
                    size_kb = os.path.getsize(fpath) // 1024 if os.path.exists(fpath) else 0
                    ts = time.strftime("%Y-%m-%d %H:%M", time.localtime(os.path.getmtime(fpath)))
                    lines.append(f"`{f}` — {size_kb} KB ({ts})")
                lines.append(f"\n{t('backup_restore_usage', lang)}")
                await message.reply("\n".join(lines))
            return
        filename = parts[2].strip()
        ok, msg = restore_backup(filename)
        if ok:
            ok2, msg2 = rebuild_and_reload_xray()
            await message.reply(t("backup_restored_ok", lang).format("✅" if ok2 else f"❌ {msg2}"))
        else:
            await message.reply(t("backup_error", lang).format(msg))

    else:
        await message.reply(t("admin_help", lang))


def get_mem_mb() -> float:
    try:
        import resource
        return resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024.0
    except Exception:
        return 0.0


async def cmd_health_handler(message: Message):
    """Public /health command."""
    tg_id = message.from_user.id
    if tg_id not in ADMIN_IDS:
        await message.reply(t("health_public", LANG_DEFAULT))
        return
    # Admin gets full health
    await cmd_admin(message)  # reuse admin handler with subcmd detection
    # But we need to handle /health specially
    with db() as conn:
        active = conn.execute(
            "SELECT COUNT(*) FROM subscriptions WHERE active=1 AND expires_at > strftime('%s','now')"
        ).fetchone()[0]
    xray_status = (await asyncio.to_thread(subprocess.run, ["systemctl", "is-active", "vpn-core-xray"], capture_output=True, text=True)).stdout.strip()
    ok, test_msg = test_xray_config(XRAY_CONFIG_PATH)
    xray_icon = '✅' if xray_status == 'active' else '❌'
    await message.reply(
        f"🏥 **Health Check**\n\n"
        f"vpn-seller-bot: ✅ active\n"
        f"vpn-core-xray: {xray_icon} {xray_status}\n"
        f"Xray config: {'✅ valid' if ok else '❌ ' + test_msg}\n"
        f"Активных клиентов: {active}\n"
        f"Память: {get_mem_mb():.0f} MB"
    )


async def inline_query_handler(query):
    """Handle @poliakabot inline mode: quick access to VPN link."""
    tg_id = query.from_user.id
    _conn = db()
    lang = get_lang(_conn, tg_id)
    _conn.close()

    sub = latest_sub(tg_id)
    results = []
    if sub and sub["active"] and sub["expires_at"] > int(time.time()):
        link = build_vless_link(sub["uuid"])
        backup_link = build_vless_backup_link(sub["uuid"])
        from aiogram.types import InlineQueryResultArticle, InputTextMessageContent
        expires = time.strftime('%Y-%m-%d %H:%M', time.localtime(sub['expires_at']))
        results.append(
            InlineQueryResultArticle(
                id="my_access",
                title=t("inline_my_access", lang),
                description=f"{t('inline_active_desc', lang)} {expires}",
                input_message_content=InputTextMessageContent(
                    t("inline_access_msg", lang, link, backup_link, expires)
                ),
            )
        )
        results.append(
            InlineQueryResultArticle(
                id="my_qr",
                title=t("inline_my_qr", lang),
                description=t("inline_qr_desc", lang),
                input_message_content=InputTextMessageContent(
                    t("inline_qr_msg", lang, expires)
                ),
            )
        )
    else:
        from aiogram.types import InlineQueryResultArticle, InputTextMessageContent
        results.append(
            InlineQueryResultArticle(
                id="no_sub",
                title=t("inline_no_sub_title", lang),
                description=t("inline_no_sub_desc", lang),
                input_message_content=InputTextMessageContent(
                    t("inline_no_sub_msg", lang)
                ),
            )
        )
    await query.answer(results, cache_time=60)


async def cmd_start(message: Message):
    # Support referral: /start <referrer_tg_id>
    ref = None
    parts = (message.text or "").split(maxsplit=1)
    if len(parts) == 2 and parts[1].isdigit():
        ref = int(parts[1])
        if ref == message.from_user.id:
            ref = None

    with db() as conn:
        conn.execute(
            "INSERT INTO users (tg_id, created_at, referrer_tg_id) VALUES (?,?,?) "
            "ON CONFLICT(tg_id) DO UPDATE SET referrer_tg_id=COALESCE(users.referrer_tg_id, excluded.referrer_tg_id)",
            (message.from_user.id, int(time.time()), ref),
        )
        conn.commit()

    await upsert_main_message(message.bot, message.chat.id, message.from_user.id)


async def cmd_promo(message: Message):
    _conn = db()
    lang = get_lang(_conn, message.from_user.id)
    _conn.close()

    parts = (message.text or "").split(maxsplit=1)
    if len(parts) < 2:
        await message.reply(t("promo_usage", lang))
        return
    code = normalize_promo(parts[1])
    ok, msg_key = promo_can_redeem(message.from_user.id, code)
    if not ok:
        await message.reply(t(msg_key, lang))
        return
    promo_redeem(message.from_user.id, code)
    row = promo_get(code)
    await message.reply(
        f"{t('promo_activated', lang)} {code}\n"
        f"{t('promo_type', lang)} {row['kind']}\n"
        f"{t('promo_value', lang)} {row['value']}\n\n"
        f"{t('promo_now_buy', lang)}"
    )


async def cmd_lang_handler(message: Message):
    """Handle /lang command — show language selection."""
    _conn = db()
    lang = get_lang(_conn, message.from_user.id)
    _conn.close()

    kb = InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="🇷🇺 Русский", callback_data="lang_set_ru"),
                InlineKeyboardButton(text="🇬🇧 English", callback_data="lang_set_en"),
            ]
        ]
    )
    await message.reply(t("lang_select", lang), reply_markup=kb)


async def on_callback(query: CallbackQuery):
    bot = query.bot
    tg_id = query.from_user.id
    data = query.data or ""
    log.info("callback tg_id=%s data=%s", tg_id, data)

    # Resolve user's language
    _conn = db()
    lang = get_lang(_conn, tg_id)
    _conn.close()

    # Language change callbacks
    if data in ("lang_set_ru", "lang_set_en"):
        await query.answer()
        new_lang = "ru" if data == "lang_set_ru" else "en"
        _conn = db()
        set_lang(_conn, tg_id, new_lang)
        _conn.close()
        msg_key = "lang_set_ru" if new_lang == "ru" else "lang_set_en"
        await upsert_main_message(bot, query.message.chat.id, tg_id)
        await clear_keyboard(bot, query.message.chat.id, query.message.message_id)
        await bot.send_message(query.message.chat.id, t(msg_key, new_lang))
        return

    if data == "lang":
        await query.answer()
        kb = InlineKeyboardMarkup(
            inline_keyboard=[
                [
                    InlineKeyboardButton(text="🇷🇺 Русский", callback_data="lang_set_ru"),
                    InlineKeyboardButton(text="🇬🇧 English", callback_data="lang_set_en"),
                ]
            ]
        )
        await bot.send_message(query.message.chat.id, t("lang_select", lang), reply_markup=kb)
        return

    # Always ack callbacks quickly; ignore if too old.
    try:
        await query.answer()
    except Exception as e:
        log.warning(f'ex: {e}')

    async def create_invoice_for_days(days: int, usdt_price: float, promo_code: str | None = None):
        # apply promo if present
        bonus_days = 0
        promo_desc = ""
        final_usdt = usdt_price
        if promo_code:
            final_usdt, bonus_days, promo_desc = promo_apply_price(usdt_price, promo_code)

        ton_amount = await get_ton_price_for_usdt(final_usdt)
        desc = f"VPN {days} days"
        if promo_desc:
            desc += f" ({promo_desc})"

        inv = await cryptobot_request(
            "createInvoice",
            {
                "asset": "TON",
                "amount": str(ton_amount),
                "description": desc,
                "hidden_message": t("invoice_hidden_msg", lang),
                "allow_anonymous": False,
            },
        )
        invoice_id = str(inv["invoice_id"])
        pay_url = inv["pay_url"]

        import json
        meta = json.dumps(
            {
                "days": days,
                "base_usdt": usdt_price,
                "final_usdt": final_usdt,
                "promo": promo_code,
                "bonus_days": bonus_days,
            },
            ensure_ascii=False,
        )

        with db() as conn:
            conn.execute(
                "INSERT INTO invoices (tg_id, invoice_id, asset, amount, status, created_at, meta) VALUES (?,?,?,?,?,?,?)",
                (tg_id, invoice_id, "TON", float(ton_amount), "active", int(time.time()), meta),
            )
            conn.commit()

        await upsert_main_message(bot, query.message.chat.id, tg_id)
        await clear_keyboard(bot, query.message.chat.id, query.message.message_id)
        invoice_text = (
            t("invoice_created", lang, ton_amount, pay_url) + "\n\n" +
            t("invoice_tariff", lang, days)
        )
        if promo_code and promo_desc:
            invoice_text += "\n" + t("invoice_promo", lang, promo_code, promo_desc)
        if bonus_days:
            invoice_text += "\n" + t("invoice_bonus", lang, bonus_days)
        invoice_text += "\n\n" + t("invoice_autocheck", lang, AUTOCHECK_TIMEOUT // 60)

        await bot.send_message(query.message.chat.id, invoice_text)

        # Start auto-check (one per user)
        old = AUTO_CHECK_TASKS.get(tg_id)
        if old and not old.done():
            old.cancel()
        AUTO_CHECK_TASKS[tg_id] = asyncio.create_task(auto_check_invoice(bot, query.message.chat.id, tg_id, invoice_id))
        AUTO_CHECK_TASKS[tg_id].add_done_callback(lambda t, tid=tg_id: AUTO_CHECK_TASKS.pop(tid, None))

    # Stars payment callbacks
    if data in ("stars_buy_30", "stars_buy_90", "stars_buy_180"):
        await upsert_main_message(bot, query.message.chat.id, tg_id)
        await clear_keyboard(bot, query.message.chat.id, query.message.message_id)

        if data == "stars_buy_30":
            await send_stars_invoice(bot, query.message.chat.id, tg_id, SUB_DAYS_30, STARS_PRICE_30, lang)
        elif data == "stars_buy_90":
            await send_stars_invoice(bot, query.message.chat.id, tg_id, SUB_DAYS_90, STARS_PRICE_90, lang)
        elif data == "stars_buy_180":
            await send_stars_invoice(bot, query.message.chat.id, tg_id, SUB_DAYS_180, STARS_PRICE_180, lang)
        return

    # Buy buttons now show payment method choice
    if data in ("buy", "buy_30", "buy_90", "buy_180"):
        if not SERVER_IP or not VLESS_PBK or not VLESS_SID:
            await bot.send_message(query.message.chat.id, t("config_not_set", lang))
            return

        # Map tariff to buy/ton callback keys
        tariff_key = data if data != "buy" else "buy_30"
        mapping = {"buy_30": "buy_30", "buy_90": "buy_90", "buy_180": "buy_180"}

        await upsert_main_message(bot, query.message.chat.id, tg_id)
        await clear_keyboard(bot, query.message.chat.id, query.message.message_id)

        # Show payment method choice
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text=t("btn_pay_stars", lang), callback_data=f"stars_{tariff_key}")],
            [InlineKeyboardButton(text=t("btn_pay_ton", lang), callback_data=f"ton_{tariff_key}")],
        ])
        await bot.send_message(
            query.message.chat.id,
            f"{t('payment_method_choice', lang)}\n\n"
            f"⭐ {t('stars_desc', lang)}\n\n"
            f"💎 {t('main_payment', lang)}",
            reply_markup=kb,
        )
        return

    # TON payment callbacks (after user chose CryptoBot)
    if data in ("ton_buy_30", "ton_buy_90", "ton_buy_180"):
        await upsert_main_message(bot, query.message.chat.id, tg_id)
        await clear_keyboard(bot, query.message.chat.id, query.message.message_id)

        # detect promo
        promo_code = None
        with db() as conn:
            row = conn.execute(
                "SELECT code FROM promo_redemptions WHERE tg_id=? ORDER BY redeemed_at DESC LIMIT 1",
                (tg_id,),
            ).fetchone()
            if row:
                promo_code = str(row["code"])

        if data == "ton_buy_30":
            await create_invoice_for_days(SUB_DAYS_30, PRICE_USDT_30, promo_code)
        elif data == "ton_buy_90":
            await create_invoice_for_days(SUB_DAYS_90, PRICE_USDT_90, promo_code)
        elif data == "ton_buy_180":
            await create_invoice_for_days(SUB_DAYS_180, PRICE_USDT_180, promo_code)
        return

    # Check button with specific invoice_id (e.g. from proxy purchase)
    if data.startswith("check_"):
        invoice_id = data[6:]
        inv = None
        with db() as conn:
            inv = conn.execute(
                "SELECT * FROM invoices WHERE invoice_id=? AND tg_id=? ORDER BY id DESC LIMIT 1",
                (invoice_id, tg_id),
            ).fetchone()
        if not inv:
            await bot.send_message(query.message.chat.id, t("no_invoices", lang))
            return
        data = "check"

    if data == "check":
        inv = latest_invoice(tg_id)
        if not inv:
            await upsert_main_message(bot, query.message.chat.id, tg_id)
            await clear_keyboard(bot, query.message.chat.id, query.message.message_id)
            await bot.send_message(query.message.chat.id, t("no_invoices", lang))
            return

        # If latest invoice in DB is still active, but user already paid an older one,
        # we still want to grant access. So if there exists any paid invoice not yet granted,
        # handle it first.
        with db() as conn:
            paid = conn.execute(
                "SELECT * FROM invoices WHERE tg_id=? AND status='paid' ORDER BY id DESC LIMIT 1",
                (tg_id,),
            ).fetchone()
        if paid:
            sub = latest_sub(tg_id)
            if not sub or sub["expires_at"] < int(time.time()) - 60:
                inv = paid

        log.info("check invoice_id=%s status_in_db=%s", inv["invoice_id"], inv["status"])
        res = await cryptobot_request("getInvoices", {"invoice_ids": [inv["invoice_id"]]})
        if not res.get("items"):
            await upsert_main_message(bot, query.message.chat.id, tg_id)
            await clear_keyboard(bot, query.message.chat.id, query.message.message_id)
            await bot.send_message(query.message.chat.id, t("invoice_not_found", lang))
            return

        item = res["items"][0]
        status = item.get("status")
        log.info("cryptobot invoice_id=%s status=%s", inv["invoice_id"], status)

        with db() as conn:
            conn.execute(
                "UPDATE invoices SET status=? WHERE invoice_id=?",
                (status, inv["invoice_id"]),
            )
            conn.commit()

        if status != "paid":
            await upsert_main_message(bot, query.message.chat.id, tg_id)
            await clear_keyboard(bot, query.message.chat.id, query.message.message_id)
            await bot.send_message(query.message.chat.id, t("invoice_status", lang, status))
            return

        log.info("invoice paid -> provisioning")
        # idempotency: don't grant twice
        if inv["fulfilled_at"]:
            await bot.send_message(query.message.chat.id, t("payment_processed", lang))
            return

        days = SUB_DAYS_30
        bonus_days = 0
        try:
            if inv["meta"]:
                import json
                meta = json.loads(inv["meta"])
                days = int(meta.get("days") or days)
                bonus_days = int(meta.get("bonus_days") or 0)
        except Exception as e:
            log.warning(f'ex: {e}')

        await provision_access(bot, query.message.chat.id, tg_id, days=days, bonus_days=bonus_days)
        with db() as conn:
            conn.execute(
                "UPDATE invoices SET fulfilled_at=? WHERE invoice_id=? AND fulfilled_at IS NULL",
                (int(time.time()), inv["invoice_id"]),
            )
            conn.commit()
        return

    if data == "status":
        await upsert_main_message(bot, query.message.chat.id, tg_id)
        await clear_keyboard(bot, query.message.chat.id, query.message.message_id)
        return

    if data == "trial":
        await upsert_main_message(bot, query.message.chat.id, tg_id)
        await clear_keyboard(bot, query.message.chat.id, query.message.message_id)

        used = get_trial_used(tg_id)
        if used >= TRIAL_MAX_PER_USER:
            await bot.send_message(query.message.chat.id, t("trial_used", lang))
            return

        if not SERVER_IP or not VLESS_PBK or not VLESS_SID:
            await bot.send_message(query.message.chat.id, t("config_not_set", lang))
            return

        client_uuid = create_client_id(email=f"trial-tg{tg_id}")
        sub = create_or_extend_sub_trial(tg_id, client_uuid, TRIAL_MINUTES)
        set_trial_used(tg_id)

        ok, msg = rebuild_and_restart_xray()
        if not ok:
            log.error("xray rebuild/restart failed: %s", msg)
            await bot.send_message(query.message.chat.id, f"{t('support_xray_fail', lang)}\n{msg}")

        link = build_vless_link(sub["uuid"])
        png = qr_png_bytes(link)
        await bot.send_message(
            query.message.chat.id,
            t("trial_activated", lang, TRIAL_MINUTES) + "\n" +
            f"{t('trial_active_until', lang)} {time.strftime('%Y-%m-%d %H:%M', time.localtime(sub['expires_at']))}\n\n" +
            t("trial_like_it", lang),
        )
        await bot.send_message(query.message.chat.id, link)
        await bot.send_photo(query.message.chat.id, BufferedInputFile(png, filename="trial.png"))
        return

    if data == "promo":
        await upsert_main_message(bot, query.message.chat.id, tg_id)
        await clear_keyboard(bot, query.message.chat.id, query.message.message_id)
        await bot.send_message(query.message.chat.id, t("promo_enter", lang))
        return

    if data == "my_access":

        sub = latest_sub(tg_id)
        await upsert_main_message(bot, query.message.chat.id, tg_id)
        await clear_keyboard(bot, query.message.chat.id, query.message.message_id)
        if not sub or not sub["active"]:
            await bot.send_message(query.message.chat.id, t("no_active_sub", lang))
            return
        link = build_vless_link(sub["uuid"])
        png = qr_png_bytes(link)
        expires = time.strftime('%Y-%m-%d %H:%M', time.localtime(sub['expires_at']))
        traffic = get_traffic_stats(lang)
        msg = (
            f"{t('your_access', lang)}\n"
            f"{t('trial_active_until', lang)} {expires}\n\n"
            f"{t('payment_reimport', lang)}"
        )
        if traffic:
            msg += "\n\n" + traffic
        await bot.send_message(query.message.chat.id, msg)
        await bot.send_message(query.message.chat.id, link)
        await bot.send_photo(query.message.chat.id, BufferedInputFile(png, filename="vpn.png"))
        return

    if data == "wg_access":
        await upsert_main_message(bot, query.message.chat.id, tg_id)
        await clear_keyboard(bot, query.message.chat.id, query.message.message_id)
        sub = latest_sub(tg_id)
        if not sub or not sub["active"] or sub["expires_at"] <= int(time.time()):
            await bot.send_message(query.message.chat.id, t("no_active_sub_wg", lang))
            return

        # Check if WG already configured
        if sub["wg_privkey"]:
            wg_ip = sub["wg_ip"] or f"{WG_SUBNET}.2"
            wg_cfg_clean = build_wireguard_config(sub["wg_privkey"], wg_ip, sub["wg_pubkey"], amnezia=False)
            wg_cfg_awg = build_wireguard_config(sub["wg_privkey"], wg_ip, sub["wg_pubkey"], amnezia=True)
            expires = time.strftime('%Y-%m-%d %H:%M', time.localtime(sub['expires_at']))
            png = qr_png_bytes(wg_cfg_clean)
            await bot.send_message(
                query.message.chat.id,
                f"{t('wg_header', lang)}\n"
                f"{t('wg_active_until', lang)} {expires}\n"
                f"IP: {sub['wg_ip']}\n\n"
                f"{t('wg_std_header', lang)}\n\n"
                f"{t('wg_awg_header', lang)}\n\n"
                f"{t('wg_qr_note', lang)}"
            )
            await bot.send_photo(query.message.chat.id, BufferedInputFile(png, filename="wireguard.png"))
            await bot.send_message(query.message.chat.id, f"```\n{wg_cfg_clean}```")
            await bot.send_message(query.message.chat.id, f"```\n{wg_cfg_awg}```")
            return

        # Generate new WG keys
        try:
            wg_priv = (await asyncio.to_thread(subprocess.run, ["wg", "genkey"], capture_output=True, text=True, timeout=5)).stdout.strip()
            wg_ip = get_next_wg_ip()
            ok, pubkey_or_err = add_wg_peer(wg_priv, wg_ip)
            if not ok:
                await bot.send_message(query.message.chat.id, f"{t('wg_error', lang)} {pubkey_or_err}")
                return

            with db() as conn:
                conn.execute(
                    "UPDATE subscriptions SET wg_ip=?, wg_privkey=?, wg_pubkey=? WHERE id=?",
                    (wg_ip, wg_priv, pubkey_or_err, sub["id"]),
                )
                conn.commit()

            wg_cfg_clean = build_wireguard_config(wg_priv, wg_ip, pubkey_or_err, amnezia=False)
            wg_cfg_awg = build_wireguard_config(wg_priv, wg_ip, pubkey_or_err, amnezia=True)
            expires = time.strftime('%Y-%m-%d %H:%M', time.localtime(sub['expires_at']))
            png = qr_png_bytes(wg_cfg_clean)
            await bot.send_message(
                query.message.chat.id,
                f"{t('wg_header_new', lang)}\n"
                f"{t('wg_active_until', lang)} {expires}\n"
                f"IP: {wg_ip}\n\n"
                f"{t('wg_new_note', lang)}"
            )
            await bot.send_photo(query.message.chat.id, BufferedInputFile(png, filename="wireguard.png"))
            await bot.send_message(query.message.chat.id, f"```\n{wg_cfg_clean}```")
            await bot.send_message(query.message.chat.id, f"```\n{wg_cfg_awg}```")
        except Exception as e:
            log.exception("WG keygen failed for tg_id=%s", tg_id)
            await bot.send_message(query.message.chat.id, f"{t('wg_error_generic', lang)} {e}")
        return

    if data == "referral":
        await upsert_main_message(bot, query.message.chat.id, tg_id)
        await clear_keyboard(bot, query.message.chat.id, query.message.message_id)
        ref_link = f"https://t.me/{(await bot.get_me()).username}?start={tg_id}"
        # Count referrals
        with db() as conn:
            refs = conn.execute(
                "SELECT COUNT(*) FROM users WHERE referrer_tg_id=?", (tg_id,)
            ).fetchone()[0]
        await bot.send_message(
            query.message.chat.id,
            f"{t('ref_title', lang)}\n\n"
            f"{t('ref_desc', lang, REFERRAL_BONUS_DAYS)}\n\n"
            f"{t('ref_your_link', lang)}\n`{ref_link}`\n\n"
            f"{t('ref_invited', lang, refs)}\n"
            f"{t('ref_bonus_note', lang)}",
        )
        return

    if data == "help":
        await bot.send_message(
            query.message.chat.id,
            f"{t('help_title', lang)}\n\n"
            f"{t('help_android', lang)}\n\n"
            f"{t('help_ios', lang)}\n\n"
            f"{t('help_windows', lang)}\n\n"
            f"{t('help_macos', lang)}\n\n"
            f"{t('help_reimport', lang)}",
        )
        return

    if data == "xkeen":
        sub = latest_sub(tg_id)
        await upsert_main_message(bot, query.message.chat.id, tg_id)
        await clear_keyboard(bot, query.message.chat.id, query.message.message_id)
        if not sub or not sub["active"] or sub["expires_at"] <= int(time.time()):
            await bot.send_message(query.message.chat.id, t("no_active_sub_wg", lang))
            return

        xkeen_cfg = build_xkeen_config(sub["uuid"])
        filename = f"xkeen_vpn_{tg_id}.json"
        cfg_file = BufferedInputFile(xkeen_cfg.encode("utf-8"), filename=filename)
        expires = time.strftime('%Y-%m-%d %H:%M', time.localtime(sub['expires_at']))
        await bot.send_document(
            query.message.chat.id, cfg_file,
            caption=f"🌀 Keenetic конфиг (VLESS+REALITY)\nАктивен до: {expires}\n\n1) Keenetic → Управление → Загрузить конфиг\n2) Выбери файл {filename}\n3) Примени"
        )
        return

    if data == "proxy_buy":
        await upsert_main_message(bot, query.message.chat.id, tg_id)
        await clear_keyboard(bot, query.message.chat.id, query.message.message_id)
        # Проверим — есть ли активный прокси
        proxy_sub = latest_sub_type(tg_id, 'proxy')
        if proxy_sub and proxy_sub["active"] and proxy_sub["expires_at"] > int(time.time()):
            expires = time.strftime('%Y-%m-%d %H:%M', time.localtime(proxy_sub['expires_at']))
            await bot.send_message(query.message.chat.id, t("proxy_access", lang).format(
                server=PROXY_SERVER, port=PROXY_PORT, secret=PROXY_SECRET, expires=expires))
            return
        # Показать описание и кнопку покупки
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text=t("btn_proxy", lang), callback_data="buy_proxy_l1")],
        ])
        await bot.send_message(query.message.chat.id, t("proxy_desc", lang), reply_markup=kb)
        return

    if data == "buy_proxy_l1":
        await clear_keyboard(bot, query.message.chat.id, query.message.message_id)
        # Получить курс TON
        ton_amount = await get_ton_price_for_usdt(0.50)
        # Создать инвойс через CryptoBot
        inv = await cryptobot_request(
            "createInvoice",
            {
                "asset": "TON",
                "amount": str(ton_amount),
                "description": "MTProto Proxy 30 days",
                "allow_anonymous": False,
            },
        )
        if not inv or "invoice_id" not in inv:
            await bot.send_message(query.message.chat.id, t("invoice_error", lang))
            return
        invoice_id = str(inv["invoice_id"])
        pay_url = inv["pay_url"]
        # Сохранить инвойс в БД
        import json
        meta = json.dumps({"type": "proxy", "days": 30}, ensure_ascii=False)
        with db() as conn:
            conn.execute(
                "INSERT INTO invoices (tg_id, invoice_id, asset, amount, status, created_at, meta) VALUES (?,?,?,?,?,?,?)",
                (tg_id, invoice_id, "TON", float(ton_amount), "active", int(time.time()), meta),
            )
            conn.commit()
        # Запустить фоновую проверку
        if tg_id in AUTO_CHECK_TASKS:
            old = AUTO_CHECK_TASKS[tg_id]
            if not old.done():
                old.cancel()
        AUTO_CHECK_TASKS[tg_id] = asyncio.create_task(auto_check_invoice(bot, query.message.chat.id, tg_id, invoice_id))
        AUTO_CHECK_TASKS[tg_id].add_done_callback(lambda t, tid=tg_id: AUTO_CHECK_TASKS.pop(tid, None))
        # Показать кнопку проверки
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text=t("btn_check", lang), callback_data=f"check_{invoice_id}")],
            [InlineKeyboardButton(text=t("btn_support", lang), callback_data="support")],
        ])
        await bot.send_message(
            query.message.chat.id,
            t("invoice_msg", lang).format(amount=ton_amount, currency="TON", usd="0.50"),
            reply_markup=kb
        )
        return

    if data == "support":
        await upsert_main_message(bot, query.message.chat.id, tg_id)
        await clear_keyboard(bot, query.message.chat.id, query.message.message_id)
        await bot.send_message(
            query.message.chat.id,
            t("support_msg", lang),
        )
        return

    await query.answer()


# ── Improvement #3: Subscription expiry notifications ──

def _get_expiring_subscriptions(now: int) -> list[tuple[dict, int]]:
    """Return active subscriptions that expire within the notification windows."""
    with db() as conn:
        # Build a query that checks each notification window
        rows = []
        for hours in NOTIFY_BEFORE_HOURS:
            window_start = now
            window_end = now + hours * 3600
            batch = conn.execute(
                """
                SELECT s.id, s.tg_id, s.uuid, s.expires_at
                FROM subscriptions s
                WHERE s.active = 1
                  AND s.expires_at > ?
                  AND s.expires_at <= ?
                  AND NOT EXISTS (
                    SELECT 1 FROM expiry_notifications en
                    WHERE en.subscription_id = s.id AND en.hours_before = ?
                  )
                """,
                (window_start, window_end, hours),
            ).fetchall()
            for r in batch:
                rows.append((dict(r), hours))
        return rows


async def _send_expiry_notification(bot: Bot, tg_id: int, expires_at: int, hours: int):
    """Send a single expiry notification to a user."""
    try:
        _conn = db()
        lang = get_lang(_conn, tg_id)
        _conn.close()
        expires_str = time.strftime("%Y-%m-%d %H:%M", time.localtime(expires_at))
        if hours >= 48:
            days = hours // 24
            text = t("expiry_days", lang, days, expires_str)
        elif hours >= 24:
            text = t("expiry_tomorrow", lang, expires_str)
        else:
            hrs = max(1, hours)
            text = t("expiry_hours", lang, hrs, expires_str)
        await bot.send_message(tg_id, text, reply_markup=kb_main(lang))
        return True
    except Exception as e:
        log.warning("Failed to notify tg_id=%s: %s", tg_id, e)
        return False


async def _run_expiry_check(bot: Bot):
    """Check for expiring subscriptions and notify users. Idempotent per (sub, window)."""
    now = int(time.time())
    expiring = _get_expiring_subscriptions(now)
    if not expiring:
        return

    log.info("Expiry check: %d subscription(s) in notification window", len(expiring))
    for sub_data, hours in expiring:
        sent = await _send_expiry_notification(bot, sub_data["tg_id"], sub_data["expires_at"], hours)
        if sent:
            with db() as conn:
                conn.execute(
                    "INSERT OR IGNORE INTO expiry_notifications (subscription_id, tg_id, hours_before, sent_at) VALUES (?,?,?,?)",
                    (sub_data["id"], sub_data["tg_id"], hours, now),
                )
                conn.commit()


# ── /test diagnostics command ──

BACKUP_DIR = os.environ.get("BACKUP_DIR", "/opt/vpn-seller-bot/backups")
BACKUP_KEEP_DAYS = int(os.environ.get("BACKUP_KEEP_DAYS", "7"))
BACKUP_INTERVAL_SEC = int(os.environ.get("BACKUP_INTERVAL_SEC", "86400"))  # 24h
_last_backup_ts = 0


def create_backup() -> tuple[bool, str]:
    """Create a tar.gz backup of DB + WG config + Xray config. Returns (ok, path|error)."""
    os.makedirs(BACKUP_DIR, exist_ok=True)
    ts = time.strftime("%Y%m%d_%H%M%S")
    name = f"vpn_backup_{ts}.tar.gz"
    path = os.path.join(BACKUP_DIR, name)
    tmp = path + ".tmp"
    try:
        import tarfile
        with tarfile.open(tmp, "w:gz") as tar:
            for src, arc in [(DB_PATH, "vpn_seller.sqlite"),
                            (XRAY_CONFIG_PATH, "xray_config.json"),
                            (WG_CONFIG_PATH, "wg0.conf")]:
                if os.path.exists(src):
                    tar.add(src, arcname=arc)
        os.rename(tmp, path)
        # Rotate old backups
        _rotate_backups()
        global _last_backup_ts
        _last_backup_ts = int(time.time())
        size_kb = os.path.getsize(path) // 1024
        log.info("Backup created: %s (%d KB)", name, size_kb)
        return True, path
    except Exception as e:
        if os.path.exists(tmp):
            os.unlink(tmp)
        return False, str(e)


def _rotate_backups():
    """Keep only last BACKUP_KEEP_DAYS worth of backups."""
    try:
        files = sorted(
            [f for f in os.listdir(BACKUP_DIR) if f.startswith("vpn_backup_") and f.endswith(".tar.gz")],
            reverse=True
        )
        cutoff = int(time.time()) - BACKUP_KEEP_DAYS * 86400
        for f in files:
            fpath = os.path.join(BACKUP_DIR, f)
            if os.path.getmtime(fpath) < cutoff:
                os.unlink(fpath)
                log.info("Backup rotated out: %s", f)
    except Exception as e:
        log.warning(f'ex: {e}')


def list_backups() -> list[str]:
    """List backup files, newest first."""
    try:
        files = sorted(
            [f for f in os.listdir(BACKUP_DIR) if f.startswith("vpn_backup_") and f.endswith(".tar.gz")],
            reverse=True
        )
        return files
    except Exception:
        return []


def restore_backup(filename: str) -> tuple[bool, str]:
    """Restore from a backup file. Returns (ok, message)."""
    # Prevent path traversal
    filename = os.path.basename(filename)
    path = os.path.join(BACKUP_DIR, filename)
    if not os.path.realpath(path).startswith(os.path.realpath(BACKUP_DIR)):
        return False, "Invalid filename"
    if not os.path.exists(path):
        return False, "File not found"
    try:
        import tarfile
        # Restore DB
        with tarfile.open(path, "r:gz") as tar:
            # Restore to temp locations first
            tmp_db = DB_PATH + ".restore"
            tmp_xray = XRAY_CONFIG_PATH + ".restore"
            tmp_wg = WG_CONFIG_PATH + ".restore"
            for member in tar.getmembers():
                if member.name == "vpn_seller.sqlite":
                    member.name = os.path.basename(tmp_db)
                    tar.extract(member, path=os.path.dirname(tmp_db))
                    os.rename(tmp_db, DB_PATH)
                elif member.name == "xray_config.json":
                    member.name = os.path.basename(tmp_xray)
                    tar.extract(member, path=os.path.dirname(tmp_xray))
                    os.rename(tmp_xray, XRAY_CONFIG_PATH)
                elif member.name == "wg0.conf":
                    member.name = os.path.basename(tmp_wg)
                    tar.extract(member, path=os.path.dirname(tmp_wg))
                    os.rename(tmp_wg, WG_CONFIG_PATH)
        return True, "ok"
    except Exception as e:
        return False, str(e)


async def cmd_test(message: Message):
    """Handle /test — self-diagnostics for any user."""
    bot = message.bot
    tg_id = message.from_user.id
    _conn = db()
    lang = get_lang(_conn, tg_id)
    _conn.close()

    status = await message.reply(t("test_running", lang))
    lines = [t("test_title", lang) + "\n"]

    # 1. Ping
    if SERVER_IP:
        try:
            r = await asyncio.to_thread(subprocess.run, ["ping", "-c", "1", "-W", "2", SERVER_IP],
                             capture_output=True, text=True, timeout=5)
            ok = r.returncode == 0
            icon = t("test_ok" if ok else "test_fail", lang)
            ms = ""
            if ok:
                import re
                m = re.search(r"time=(\d+\.?\d*)", r.stdout)
                if m:
                    ms = f" ({m.group(1)}ms)"
            lines.append(f"{icon} {t('test_ping', lang)}{ms}")
        except Exception:
            lines.append(f"{t('test_fail', lang)} {t('test_ping', lang)}")
    else:
        lines.append(f"⚠️ {t('test_ping', lang)}: SERVER_IP not set")

    # 2. VLESS port
    if SERVER_IP and VLESS_PORT:
        try:
            sock = __import__('socket').socket(__import__('socket').AF_INET, __import__('socket').SOCK_STREAM)
            sock.settimeout(3)
            result = sock.connect_ex((SERVER_IP, VLESS_PORT))
            sock.close()
            ok = result == 0
            icon = t("test_ok" if ok else "test_fail", lang)
            lines.append(f"{icon} {t('test_port_vless', lang).format(VLESS_PORT)}")
        except Exception:
            lines.append(f"{t('test_fail', lang)} {t('test_port_vless', lang).format(VLESS_PORT)}")
    else:
        lines.append(f"⚠️ VLESS port: not configured")

    # 3. WG port
    if SERVER_IP and WG_PORT:
        try:
            sock = __import__('socket').socket(__import__('socket').AF_INET, __import__('socket').SOCK_STREAM)
            sock.settimeout(3)
            result = sock.connect_ex((SERVER_IP, WG_PORT))
            sock.close()
            ok = result == 0
            icon = t("test_ok" if ok else "test_fail", lang)
            lines.append(f"{icon} {t('test_port_wg', lang).format(WG_PORT)}")
        except Exception:
            lines.append(f"{t('test_fail', lang)} {t('test_port_wg', lang).format(WG_PORT)}")

    # 4. Xray service
    try:
        r = await asyncio.to_thread(subprocess.run, ["systemctl", "is-active", XRAY_SERVICE],
                         capture_output=True, text=True, timeout=5)
        ok = r.stdout.strip() == "active"
        icon = t("test_ok" if ok else "test_fail", lang)
        lines.append(f"{icon} {t('test_xray_status', lang)}: {r.stdout.strip()}")
    except Exception:
        lines.append(f"{t('test_fail', lang)} {t('test_xray_status', lang)}")

    # 5. Subscription
    sub = latest_sub(tg_id)
    if sub and sub["active"] and sub["expires_at"] > int(time.time()):
        exp = time.strftime("%Y-%m-%d %H:%M", time.localtime(sub["expires_at"]))
        lines.append(f"{t('test_ok', lang)} {t('test_sub_status', lang)}: {t('test_active_until', lang).format(exp)}")
    else:
        lines.append(f"⚠️ {t('test_sub_status', lang)}: {t('test_no_sub', lang)}")

    # 6. Server load
    lines.append(f"\n**{t('test_server_load', lang)}:**")
    try:
        load = os.getloadavg()
        lines.append(f"{t('test_cpu', lang)}: {load[0]:.1f} / {load[1]:.1f} / {load[2]:.1f}")
    except Exception as e:
        log.warning(f'ex: {e}')
    try:
        mem = get_mem_mb()
        lines.append(f"{t('test_mem', lang)}: {mem:.0f} MB")
    except Exception as e:
        log.warning(f'ex: {e}')
    try:
        disk = (await asyncio.to_thread(subprocess.run, ["df", "-h", "/"], capture_output=True, text=True, timeout=5)).stdout
        for line in disk.strip().split("\n")[1:]:
            parts = line.split()
            if len(parts) >= 5:
                lines.append(f"{t('test_disk', lang)}: {parts[2]}/{parts[1]} ({parts[4]})")
                break
    except Exception as e:
        log.warning(f'ex: {e}')

    await status.edit_text("\n".join(lines))


# ── Background scheduler ──

async def _scheduler_loop(bot: Bot, stop_event: asyncio.Event):
    """Background task: expiry checks + DB reconciliation on a timer."""
    log.info("Scheduler started (notify_interval=%ds, notify_windows=%s)",
             NOTIFY_INTERVAL_SEC, NOTIFY_BEFORE_HOURS)
    while not stop_event.is_set():
        try:
            # Reconcile expired subscriptions
            changed = reconcile_subscriptions()
            if changed:
                log.info("Scheduler: deactivated %d expired subscription(s)", changed)
                # Rebuild xray config to remove expired clients
                ok, msg = rebuild_and_reload_xray()
                if not ok:
                    log.error("Scheduler: xray rebuild failed: %s", msg)
                else:
                    log.info("Scheduler: xray config rebuilt (%d active)", len(list_active_uuids()))

            # Auto-clean expired invoices (>24h old active -> expired)
            now_ts = int(time.time())
            with db() as conn:
                cur = conn.execute(
                    "UPDATE invoices SET status='expired' WHERE status='active' AND created_at < ?",
                    (now_ts - 86400,),
                )
                if cur.rowcount:
                    log.info("Scheduler: expired %d stale invoice(s)", cur.rowcount)
                conn.commit()

            # Check for expiry notifications
            await _run_expiry_check(bot)

            # Auto-backup
            global _last_backup_ts
            if now_ts - _last_backup_ts >= BACKUP_INTERVAL_SEC:
                ok, result = create_backup()
                if ok:
                    log.info("Scheduler: auto-backup created %s", os.path.basename(result))
                else:
                    log.warning("Scheduler: auto-backup failed: %s", result)

        except Exception:
            log.exception("Scheduler tick failed")

        # Sleep in small chunks so we can react to stop_event quickly
        remaining = NOTIFY_INTERVAL_SEC
        while remaining > 0 and not stop_event.is_set():
            await asyncio.sleep(min(10, remaining))
            remaining -= 10

    log.info("Scheduler stopped")


async def main():
    if not BOT_TOKEN:
        raise RuntimeError("TELEGRAM_BOT_TOKEN is not set")

    # Single-instance lock to avoid Telegram getUpdates conflicts
    lock_path = os.environ.get("BOT_LOCK_PATH", "./data/bot.lock")
    os.makedirs(os.path.dirname(lock_path), exist_ok=True)
    try:
        import fcntl

        lock_fh = open(lock_path, "w")
        fcntl.flock(lock_fh, fcntl.LOCK_EX | fcntl.LOCK_NB)
        lock_fh.write(str(os.getpid()))
        lock_fh.flush()
    except Exception:
        raise RuntimeError(f"Another bot instance is already running (lock: {lock_path}).")

    init_db()

    # Startup: reconcile and rebuild xray config
    log.info("Startup reconciliation...")
    try:
        changed = reconcile_subscriptions()
        if changed:
            log.info("Startup: deactivated %d expired subscription(s)", changed)
        ok, msg = rebuild_and_reload_xray()
        if ok:
            log.info("Startup: xray config synced (%d active clients)", len(list_active_uuids()))
        else:
            log.error("Startup: xray rebuild failed: %s", msg)
    except Exception:
        log.exception("Startup reconciliation failed")

    bot = Bot(token=BOT_TOKEN)
    dp = Dispatcher()

    dp.message.register(cmd_start, CommandStart())
    dp.message.register(cmd_promo, F.text.startswith("/promo"))
    dp.message.register(cmd_admin, F.text.startswith("/admin"))
    dp.message.register(cmd_health_handler, F.text == "/health")
    dp.message.register(cmd_lang_handler, F.text == "/lang")
    dp.message.register(cmd_test, F.text == "/test")

    # ── Telegram Stars payment handlers ──
    from aiogram.types import PreCheckoutQuery

    @dp.pre_checkout_query()
    async def on_pre_checkout(pre_checkout_query: PreCheckoutQuery):
        """Always accept pre-checkout queries for Stars payments."""
        log.info("pre_checkout_query: id=%s from=%s amount=%s currency=%s",
                 pre_checkout_query.id, pre_checkout_query.from_user.id,
                 pre_checkout_query.total_amount, pre_checkout_query.currency)
        await pre_checkout_query.answer(ok=True)

    @dp.message(F.successful_payment)
    async def on_successful_payment(message: Message):
        """Handle successful Stars payment — provision VPN."""
        tg_id = message.from_user.id
        chat_id = message.chat.id
        import json

        try:
            payload = json.loads(message.successful_payment.invoice_payload)
            days = int(payload.get("days", SUB_DAYS_30))
        except Exception:
            days = SUB_DAYS_30

        # Get user language
        lang = "ru"
        try:
            _conn = db()
            lang = get_lang(_conn, tg_id)
            _conn.close()
        except Exception:
            pass

        charge_id = message.successful_payment.telegram_payment_charge_id
        log.info("Stars payment: tg=%s days=%s charge=%s", tg_id, days, charge_id)

        # Provision VPN
        await provision_access(bot, chat_id, tg_id, days=days)

        # Confirmation message
        await bot.send_message(
            chat_id,
            t("stars_payment_confirmed", lang, charge_id),
            reply_markup=kb_main(lang),
        )

    dp.callback_query.register(on_callback)

    # ── Inline mode handler ──
    from aiogram.types import InlineQuery
    dp.inline_query.register(inline_query_handler)

    # ── Start background scheduler (Improvement #3) ──
    stop_event = asyncio.Event()
    scheduler_task = asyncio.create_task(_scheduler_loop(bot, stop_event))

    # ── Graceful shutdown handler ──
    loop = asyncio.get_running_loop()

    def _shutdown():
        log.info("Received shutdown signal, stopping scheduler...")
        stop_event.set()

    for sig in (signal.SIGTERM, signal.SIGINT):
        try:
            loop.add_signal_handler(sig, _shutdown)
        except NotImplementedError:
            pass  # Windows fallback

    try:
        log.info("Bot starting (improved: reload+rollback, rate-cache, expiry-notify, user=vpn-bot, i18n=EN/RU)")
        await dp.start_polling(bot)
    finally:
        stop_event.set()
        await scheduler_task
        lock_fh.close()
        log.info("Bot shut down cleanly")


if __name__ == "__main__":
    asyncio.run(main())
