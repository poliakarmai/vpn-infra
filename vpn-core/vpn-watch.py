#!/usr/bin/env python3
"""
VPN Live Traffic Monitor
Checks: xray service, Reality port, live traffic rate, recent errors,
        conntrack overflow detection (auto-restart on >500 dead sessions).

Usage: python3 vpn-watch.py        # one-shot check → writes JSON
       python3 vpn-watch.py --live # one-shot + print to stdout

Cron: */5 * * * * /opt/vpn-core/vpn-watch.py
"""

import json
import os
import subprocess
import sys
import time

STATUS_FILE = "/opt/vpn-core/conf/vpn-watch-status.json"
PORT = 4443
SERVICE = "vpn-core-xray"
XRAY_LOG = "/var/log/xray/access.log"
CONN_LIMIT = 500
MIN_ESTABLISHED_PCT = 10


def run(cmd, timeout=5):
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        return r.stdout.strip(), r.returncode
    except Exception as e:
        return str(e), 1


def get_service_status():
    out, code = run(["systemctl", "is-active", SERVICE])
    return out if code == 0 else f"inactive ({out})"


def get_port_status():
    out, code = run(["ss", "-tln", f"src :{PORT}"])
    return "open" if f":{PORT}" in out else "closed"


def get_live_traffic():
    """Get current rx/tx bytes from /proc/net/dev for ens3."""
    try:
        with open("/proc/net/dev") as f:
            for line in f:
                if "ens3:" in line:
                    parts = line.split()
                    rx = int(parts[1])
                    tx = int(parts[9])
                    return rx, tx
    except Exception:
        return 0, 0
    return 0, 0


def get_hourly_delta():
    """Calculate traffic delta over elapsed time."""
    rx1, tx1 = get_live_traffic()

    prev_file = "/opt/vpn-core/conf/vpn-watch-prev.json"
    prev = {}
    if os.path.exists(prev_file):
        try:
            with open(prev_file) as f:
                prev = json.load(f)
        except Exception:
            pass

    now = time.time()
    prev_rx = prev.get("rx_bytes", rx1)
    prev_tx = prev.get("tx_bytes", tx1)
    prev_ts = prev.get("ts", now)

    with open(prev_file, "w") as f:
        json.dump({"rx_bytes": rx1, "tx_bytes": tx1, "ts": now}, f)

    elapsed = now - prev_ts
    if elapsed < 10:
        return 0, 0, 0

    rx_rate = int((rx1 - prev_rx) / elapsed) if elapsed > 0 else 0
    tx_rate = int((tx1 - prev_tx) / elapsed) if elapsed > 0 else 0

    return rx_rate, tx_rate, int(elapsed)


def get_xray_errors():
    """Count recent error lines in xray access log."""
    if not os.path.exists(XRAY_LOG):
        return 0
    try:
        errors = 0
        with open(XRAY_LOG, errors="ignore") as f:
            for line in f:
                low = line.lower()
                if any(kw in low for kw in ("rejected", "error", "failed", "timeout")):
                    errors += 1
        return errors
    except Exception:
        return -1


def get_connection_stats():
    """Count total and established TCP connections on Reality port.
    Returns (total, established)."""
    try:
        # Все TCP-соединения к порту
        total_out, _ = run(["ss", "-tn", f"sport = :{PORT}"])
        total = len([l for l in total_out.split("\n") if l.strip() and "State" not in l])

        # Только ESTABLISHED
        est_out, _ = run(["ss", "-tn", "state", "established", f"sport = :{PORT}"])
        established = len([l for l in est_out.split("\n") if l.strip() and "State" not in l])

        return total, established
    except Exception:
        return 0, 0


def check_conntrack_overflow():
    """Detect conntrack overflow: >500 connections but <10% established.
    Auto-restarts xray if triggered. Returns (was_restarted, total, established)."""
    total, established = get_connection_stats()

    if total < CONN_LIMIT:
        return False, total, established

    pct = (established / total * 100) if total > 0 else 0

    if pct >= MIN_ESTABLISHED_PCT:
        return False, total, established

    # Overflow: куча мёртвых сессий, почти нет живых → рестарт
    now = time.strftime("%Y-%m-%d %H:%M:%S")
    msg = (f"[{now}] CONNTRACK OVERFLOW: {total} conns, "
           f"{established} ESTABLISHED ({pct:.1f}%), restarting xray...")

    try:
        with open("/opt/vpn-core/conf/vpn-watch.log", "a") as f:
            f.write(msg + "\n")
    except Exception:
        pass

    run(["sudo", "systemctl", "restart", SERVICE])
    print(msg, file=sys.stderr)

    return True, total, established


def format_bytes(b):
    if b < 1024:
        return f"{b} B/s"
    elif b < 1024 * 1024:
        return f"{b / 1024:.1f} KB/s"
    else:
        return f"{b / (1024 * 1024):.1f} MB/s"


def main():
    # --- Детектор conntrack overflow (до остальных проверок) ---
    restarted, conn_total, conn_est = check_conntrack_overflow()

    service = get_service_status()
    port = get_port_status()
    rx_rate, tx_rate, elapsed = get_hourly_delta()
    errors = get_xray_errors()
    total = rx_rate + tx_rate
    active = total > 1024

    status = {
        "ts": int(time.time()),
        "service": service,
        "port_status": port,
        "traffic_active": active,
        "rx_rate": rx_rate,
        "tx_rate": tx_rate,
        "elapsed_s": elapsed,
        "xray_errors": errors,
        "rx_fmt": format_bytes(rx_rate),
        "tx_fmt": format_bytes(tx_rate),
        "connections_total": conn_total,
        "connections_established": conn_est,
        "conntrack_restarted": restarted,
    }

    with open(STATUS_FILE, "w") as f:
        json.dump(status, f)

    if "--live" in sys.argv:
        print(f"Service:  {service}")
        print(f"Port {PORT}:  {port}")
        print(f"Traffic:  {'✅ ACTIVE' if active else '⚠️ IDLE'} "
              f"({format_bytes(rx_rate)}↓ {format_bytes(tx_rate)}↑)")
        print(f"Connections: {conn_total} total, {conn_est} established")
        print(f"Errors (log): {errors}")
        if restarted:
            print("🔄 Xray restarted due to conntrack overflow!")
        print(f"Status → {STATUS_FILE}")

    is_healthy = service == "active" and port == "open" and active
    return 0 if is_healthy else 1


if __name__ == "__main__":
    sys.exit(main())
