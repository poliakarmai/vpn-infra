# Implementation Plans — VPN-инфраструктура @Poliakarbot

Сгенерированы `improve` skill 2026-06-11. Выполняй в порядке ниже если зависимости не говорят иначе.

## Execution order & status

| Plan | Title | Priority | Effort | Depends on | Status |
|------|-------|----------|--------|------------|--------|
| 001 | Убрать хардкод прокси-секретов | P1 | S | — | TODO |
| 002 | Починить платёжный flow для proxy | P1 | S | — | TODO |
| 003 | Добавить миграцию sub_type в init_db | P1 | S | — | TODO |
| 004 | SQLite: WAL-режим + индексы | P1 | S | — | TODO |
| 005 | Path traversal в restore_backup | P2 | S | — | TODO |
| 006 | Валидация конфига Xray перед rotate | P2 | S | — | TODO |
| 007 | Async-обёртки для subprocess | P2 | M | 004 | TODO |
| 008 | Очистка AUTO_CHECK_TASKS | P2 | S | — | TODO |
| 009 | vpn-watch: добавить sudo | P2 | S | — | TODO |

## Быстрые победы (Quick Wins) — без формальных планов

Эти находки имеют effort=S и могут быть сделаны без плана:

| # | Что сделать | Где |
|---|------------|-----|
| Q1 | `except Exception: pass` → `log.warning(...)` | 26 мест в bot.py |
| Q2 | Ручное `conn.close()` → `with db() as conn:` | 5 мест: :1113, :1147, :1189, :1328, :1588 |
| Q3 | `add_wg_peer` аннотация `-> bool` → `-> tuple[bool, str]` | bot.py:880 |
| Q4 | `_get_expiring_subscriptions` аннотация → `list[tuple[dict, int]]` | bot.py:2126 |
| Q5 | `latest_sub()` двойной вызов → одна переменная | bot.py:1844 |
| Q6 | Удалить мёртвую `restart_xray()` | bot.py:859-863 |

## Среднесрочные улучшения

| # | Что | Effort | План нужен? |
|---|-----|--------|-------------|
| M1 | Разбить монолит на модули (db, i18n, payments, vpn, handlers) | L | Да, characterization tests first |
| M2 | Вынести общий код (build_vless_link, rebuild_xray) в vpn_core.py | M | Нет (механический рефакторинг) |
| M3 | Разбить on_callback на отдельные handler'ы | M | Нет (aiogram F.data) |
| M4 | Дебаунс рестартов Xray (копить изменения, применять раз в N сек) | M | Да |
| M5 | Инициализировать git-репозиторий | S | Нет (`git init && git add .`) |
| M6 | Создать pyproject.toml + ruff + mypy | S | Нет |
| M7 | Создать .env.example | S | Нет |
| M8 | Создать Makefile (test, lint, format, run) | S | Нет |
| M9 | Создать README.md + AGENTS.md | S | Нет |
| M10 | Заменить print() на logging в скриптах | S | Нет |
| M11 | Добавить characterization tests (платежи, выдача ключей) | M | Да |
| M12 | N+1 в _get_expiring_subscriptions | S | Нет |

## Findings considered and rejected

- **[P-03] Admin /stats: 17 запросов** — не стоит делать сейчас. Админ-команда вызывается редко, event loop не блокируется на практике. Отложено до роста числа оплат >10K.
- **[TD-06] i18n-словарь 196 строк в bot.py** — часть плана M1 (разбиение монолита). Отдельный план избыточен.
- **[8-02] Документация рассогласована** — цифры строк (2467→2523) и fp (chrome→firefox) уже обновлены в скиллах во время аудита.
- **[8-03] Документация только в Hermes** — by-design. Hermes-скиллы — каноничный источник документации для этого проекта.
