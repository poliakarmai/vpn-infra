# Plan 005: Path traversal fix в restore_backup

> **Executor instructions**: Следуй плану. Рабочая директория: `/opt/vpn-seller-bot`.

## Status
- **Priority**: P2 | **Effort**: S | **Risk**: LOW | **Category**: security | **Planned at**: 2026-06-11

## Why

`bot.py:2262`: `path = os.path.join(BACKUP_DIR, filename)` — `filename` приходит от админской команды и не проверяется на `../`. Хотя доступ к команде только у админов, defence-in-depth требует валидации.

## Steps

### Step 1: Добавить проверку

В `restore_backup()` (bot.py:2260), после строки 2262, перед `os.path.exists`:

```python
# Prevent path traversal
filename = os.path.basename(filename)
path = os.path.join(BACKUP_DIR, filename)
if not os.path.realpath(path).startswith(os.path.realpath(BACKUP_DIR)):
    return False, "Invalid filename"
```

### Step 2: Рестарт

```bash
sudo systemctl restart vpn-seller-bot
```

## Done criteria
- [ ] `/restore ../../etc/passwd` возвращает "Invalid filename" (не пытается открыть файл)
- [ ] `/restore vpn_backup_20260610_140625.tar.gz` работает как раньше

---

# Plan 006: Валидация Xray-конфига перед ротацией доменов

## Status
- **Priority**: P2 | **Effort**: S | **Risk**: LOW | **Category**: bug | **Planned at**: 2026-06-11

## Why

`rotate-reality-domains.py:118-125` пишет конфиг и сразу делает `systemctl restart` без `xray run -test`. Битый конфиг = даунтайм 20-45 сек пока vpn-watch не откатит.

## Step

В `~/.hermes/scripts/rotate-reality-domains.py`, перед `systemctl restart` добавить:

```python
import subprocess
result = subprocess.run(["xray", "run", "-test", "-config", config_path], capture_output=True, text=True)
if result.returncode != 0:
    log.error(f"Xray config test failed: {result.stderr}")
    sys.exit(1)
```

## Done criteria
- [ ] При битом конфиге скрипт падает с ошибкой, Xray НЕ перезапускается
- [ ] При валидном — работает как раньше

---

# Plan 007: Async-обёртки для блокирующего subprocess

## Status
- **Priority**: P2 | **Effort**: M | **Risk**: LOW | **Category**: perf | **Depends on**: 004 | **Planned at**: 2026-06-11

## Why

8+ хендлеров вызывают `subprocess.run()` синхронно, блокируя asyncio event loop на секунды. Пока `/test` или `/admin health` работает — бот не отвечает другим пользователям.

## Steps

### Step 1: Создать хелпер

В bot.py добавить:

```python
async def run_async(cmd, timeout=10):
    """Run subprocess without blocking event loop."""
    proc = await asyncio.create_subprocess_exec(
        *cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
    )
    try:
        stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=timeout)
        return stdout.decode(), stderr.decode(), proc.returncode
    except asyncio.TimeoutError:
        proc.kill()
        raise
```

### Step 2: Заменить в критичных местах

| Место | Было | Стало |
|-------|------|-------|
| `test_xray_config():791` | `subprocess.run(["xray",...])` | `await run_async(["xray",...])` |
| `get_traffic_stats():1040` | `subprocess.run(["vnstat",...])` | `await run_async(["vnstat",...])` |
| `/admin health:1495` | `subprocess.run(["systemctl",...])` | `await run_async(["systemctl",...])` |
| `/test:2305,2351` | `subprocess.run(["ping"|"systemctl",...])` | `await run_async([...])` |

### Step 3: Для socket.connect_ex → asyncio.open_connection

`bot.py:2324,2339` — заменить синхронный `socket` на `asyncio.open_connection`.

## Done criteria
- [ ] `/test` не блокирует другие сообщения (проверить: запустить `/test` и одновременно `/start` — оба должны ответить)

---

# Plan 008: Очистка AUTO_CHECK_TASKS

## Status
- **Priority**: P2 | **Effort**: S | **Risk**: LOW | **Category**: bug | **Planned at**: 2026-06-11

## Why

`AUTO_CHECK_TASKS` (bot.py:315) — словарь `{tg_id: asyncio.Task}`. Задачи добавляются (line 1801), старые отменяются (1799), но завершённые НИКОГДА не удаляются. Словарь растёт с каждым новым пользователем → утечка памяти O(N).

## Step

После `task = asyncio.create_task(auto_check_invoice(...))` (line 1801) добавить:

```python
task.add_done_callback(lambda t, tid=tg_id: AUTO_CHECK_TASKS.pop(tid, None))
```

## Done criteria
- [ ] После успешной проверки инвойса запись удаляется из `AUTO_CHECK_TASKS`
- [ ] `len(AUTO_CHECK_TASKS)` не растёт монотонно со временем

---

# Plan 009: vpn-watch — добавить sudo для systemctl restart

## Status
- **Priority**: P2 | **Effort**: S | **Risk**: LOW | **Category**: bug | **Planned at**: 2026-06-11

## Why

`vpn-watch.py:148`: `run(["systemctl", "restart", SERVICE])` без `sudo`. Если cron работает не от root — авто-рестарт Xray при conntrack overflow молча не сработает.

## Step

Заменить `["systemctl", "restart", SERVICE]` на `["sudo", "systemctl", "restart", SERVICE]` (vpn-watch.py:148).

## Done criteria
- [ ] `grep "systemctl restart" /opt/vpn-core/vpn-watch.py` показывает `sudo systemctl restart`

