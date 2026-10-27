"""Тесты логики vpn-watch: порог conntrack-overflow и формат трафика.

Файл лежит в проде как сервис-крон; тестируем чистую логику — subprocess
и sysfs подменяются, ничего живого не трогаем.
"""
import importlib.util
import sys
from pathlib import Path

WATCH = Path(__file__).resolve().parent.parent / "vpn-core" / "vpn-watch.py"


def load():
    spec = importlib.util.spec_from_file_location("vpn_watch", WATCH)
    assert spec and spec.loader, f"не загрузился {WATCH}"
    mod = importlib.util.module_from_spec(spec)
    sys.modules["vpn_watch"] = mod
    spec.loader.exec_module(mod)
    return mod


vpn_watch = load()


def test_format_bytes_boundaries():
    assert vpn_watch.format_bytes(0) == "0 B/s"
    assert vpn_watch.format_bytes(1023) == "1023 B/s"
    assert vpn_watch.format_bytes(1024) == "1.0 KB/s"
    assert vpn_watch.format_bytes(1024 * 1024 - 1) == "1024.0 KB/s"
    assert vpn_watch.format_bytes(1024 * 1024) == "1.0 MB/s"


def _stats(monkeypatch, total, established, calls):
    monkeypatch.setattr(vpn_watch, "get_connection_stats", lambda: (total, established))
    monkeypatch.setattr(vpn_watch, "run", lambda cmd, timeout=5: calls.append(cmd))


def test_below_limit_no_restart(monkeypatch):
    calls = []
    _stats(monkeypatch, 499, 0, calls)
    restarted, total, est = vpn_watch.check_conntrack_overflow()
    assert (restarted, total, est) == (False, 499, 0)
    assert calls == []


def test_at_limit_but_healthy_no_restart(monkeypatch):
    calls = []
    _stats(monkeypatch, 500, 50, calls)  # ровно 10% живых
    restarted, *_ = vpn_watch.check_conntrack_overflow()
    assert restarted is False
    assert calls == []


def test_overflow_triggers_restart(monkeypatch):
    calls = []
    _stats(monkeypatch, 501, 49, calls)  # 9.8% < 10%
    restarted, total, est = vpn_watch.check_conntrack_overflow()
    assert restarted is True
    assert (total, est) == (501, 49)
    assert calls == [["sudo", "systemctl", "restart", vpn_watch.SERVICE]]


def test_zero_established_over_limit_restarts(monkeypatch):
    calls = []
    _stats(monkeypatch, 600, 0, calls)
    restarted, *_ = vpn_watch.check_conntrack_overflow()
    assert restarted is True
    assert len(calls) == 1


def test_thresholds_are_the_documented_values():
    assert vpn_watch.CONN_LIMIT == 500
    assert vpn_watch.MIN_ESTABLISHED_PCT == 10
