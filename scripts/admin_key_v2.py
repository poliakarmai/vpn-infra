#!/usr/bin/env python3
"""
Admin key generator v2 — VLESS+REALITY + Hysteria2, trial keys, auto-renew.
  python3 admin_key_v2.py grant <tg_id> <days>
  python3 admin_key_v2.py trial <tg_id>
  python3 admin_key_v2.py renew <tg_id>
  python3 admin_key_v2.py list
  python3 admin_key_v2.py remove <tg_id>
"""
import argparse, json, os, sqlite3, subprocess, sys, time, uuid, urllib.parse, shutil
from pathlib import Path

ENV_PATH = Path(__file__).resolve().parent.parent / ".env"
if ENV_PATH.exists():
    with open(ENV_PATH) as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith('#') and '=' in line:
                k, v = line.split('=', 1)
                os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))

def env(key, default=""):
    return os.environ.get(key, default).strip()

DB_PATH = env("DB_PATH", str(Path(__file__).resolve().parent.parent / "data" / "vpn_seller.sqlite"))
XRAY_CONFIG_PATH = env("XRAY_CONFIG_PATH", "/opt/vpn-core/conf/config.json")
HYSTERIA_CONFIG_PATH = "/opt/vpn-core/conf/hysteria.yaml"
SERVER_IP = env("SERVER_IP")
VLESS_PORT = int(env("VLESS_PORT", "4443"))
VLESS_SNI = env("VLESS_SNI", "www.cloudflare.com")
VLESS_FP = env("VLESS_FINGERPRINT", "chrome")
VLESS_PBK = env("VLESS_PBK")
VLESS_SID = env("VLESS_SID")
HYSTERIA_PORT = int(env("HYSTERIA_PORT", "8444"))
TRIAL_DAYS = int(env("TRIAL_DAYS", "7"))

def _read_xray_params():
    try:
        with open(XRAY_CONFIG_PATH) as f: cfg = json.load(f)
        inb = cfg["inbounds"][0]; rs = inb["streamSettings"]["realitySettings"]
        return {"sni":rs["serverNames"][0],"pbk":VLESS_PBK,"sid":rs["shortIds"][0],"port":inb["port"]}
    except: return {"sni":VLESS_SNI,"pbk":VLESS_PBK,"sid":VLESS_SID,"port":VLESS_PORT}

def db():
    conn = sqlite3.connect(DB_PATH); conn.row_factory = sqlite3.Row; return conn

def build_vless_link(client_uuid, name="vpn"):
    xp = _read_xray_params()
    p = {"type":"tcp","security":"reality","encryption":"none","sni":xp["sni"],"fp":VLESS_FP,"pbk":xp["pbk"],"sid":xp["sid"],"spx":"/","allowInsecure":"1"}
    return f"vless://{client_uuid}@{SERVER_IP}:{xp['port']}?{urllib.parse.urlencode(p)}#{urllib.parse.quote(name)}"

def build_hysteria_link(password, name="vpn-hy2"):
    return f"hysteria2://{password}@{SERVER_IP}:{HYSTERIA_PORT}?insecure=1&sni=vpn.poliakar.me#{urllib.parse.quote(name)}"

def grant_subscription(tg_id, days, note="", is_trial=False):
    now=int(time.time()); cu=str(uuid.uuid4()); hp=str(uuid.uuid4())[:16]; exp=now+days*86400
    with db() as conn:
        conn.execute("INSERT INTO subscriptions (tg_id,uuid,hysteria_pass,created_at,expires_at,active,is_trial,note) VALUES (?,?,?,?,?,1,?,?)",
                     (tg_id,cu,hp,now,exp,1 if is_trial else 0,note))
        conn.execute("INSERT OR IGNORE INTO users (tg_id,created_at) VALUES (?,?)",(tg_id,now))
        conn.commit()
    return {"tg_id":tg_id,"uuid":cu,"hysteria_pass":hp,"days":days,"expires_at":exp,"note":note,"is_trial":is_trial}

def can_request_trial(tg_id):
    with db() as conn:
        return conn.execute("SELECT COUNT(*) as c FROM subscriptions WHERE tg_id=? AND is_trial=1",(tg_id,)).fetchone()["c"]==0

def renew_subscription(tg_id, days=30):
    now=int(time.time())
    with db() as conn:
        rows=conn.execute("SELECT id,expires_at FROM subscriptions WHERE tg_id=? AND active=1 AND expires_at>?",(tg_id,now)).fetchall()
        if not rows: return None
        for r in rows:
            conn.execute("UPDATE subscriptions SET expires_at=? WHERE id=?",(max(r["expires_at"],now)+days*86400,r["id"]))
        conn.commit()
    return {"tg_id":tg_id,"count":len(rows),"days_added":days}

def list_active_uuids():
    with db() as conn:
        return [r["uuid"] for r in conn.execute("SELECT uuid FROM subscriptions WHERE active=1 AND expires_at>?",(int(time.time()),)).fetchall()]

def rebuild_xray():
    with db() as conn:
        conn.execute("UPDATE subscriptions SET active=0 WHERE active=1 AND expires_at<=?",(int(time.time()),)); conn.commit()
    active=sorted(set(list_active_uuids()))
    clients=[{"id":u,"email":f"sub-{u}"} for u in active] or [{"id":"00000000-0000-0000-0000-000000000000","email":"disabled"}]
    with open("/opt/vpn-core/conf/config.template.json") as f: cfg=json.load(f)
    cfg["inbounds"][0]["settings"]["clients"]=clients
    tmp,tbak=XRAY_CONFIG_PATH+".tmp", XRAY_CONFIG_PATH+".bak"
    if os.path.exists(XRAY_CONFIG_PATH): shutil.copy(XRAY_CONFIG_PATH,tbak)
    with open(tmp,"w") as f: json.dump(cfg,f,ensure_ascii=False,indent=2)
    os.replace(tmp,XRAY_CONFIG_PATH)
    r=subprocess.run(["/opt/vpn-core/bin/xray","run","-test","-config",XRAY_CONFIG_PATH],capture_output=True,text=True,timeout=10)
    if r.returncode!=0:
        if os.path.exists(tbak): os.replace(tbak,XRAY_CONFIG_PATH)
        print(f"❌ Config test failed",file=sys.stderr); sys.exit(1)
    subprocess.run(["sudo","systemctl","restart","vpn-core-xray"],check=True,timeout=20)
    if os.path.exists(tbak): os.remove(tbak)

def rebuild_hysteria():
    with db() as conn:
        conn.execute("UPDATE subscriptions SET active=0 WHERE active=1 AND expires_at<=?",(int(time.time()),)); conn.commit()
        rows=conn.execute("SELECT hysteria_pass FROM subscriptions WHERE active=1 AND expires_at>? AND hysteria_pass IS NOT NULL",(int(time.time()),)).fetchall()
    passwords=[r["hysteria_pass"] for r in rows] or ["DISABLED_PLACEHOLDER"]
    try:
        import yaml
        with open(HYSTERIA_CONFIG_PATH) as f: cfg=yaml.safe_load(f)
        cfg["auth"]["password"]=passwords[0]
        with open(HYSTERIA_CONFIG_PATH+".tmp","w") as f: yaml.dump(cfg,f,default_flow_style=False)
        os.replace(HYSTERIA_CONFIG_PATH+".tmp",HYSTERIA_CONFIG_PATH)
        subprocess.run(["sudo","systemctl","restart","vpn-core-hysteria"],check=True,timeout=10)
    except Exception as e:
        print(f"⚠️ Hysteria skip: {e}", file=sys.stderr)

def cmd_grant(tg_id, days, note=""):
    si=grant_subscription(tg_id,days,note)
    vless=build_vless_link(si['uuid'])
    hy2=build_hysteria_link(si['hysteria_pass'])
    rebuild_xray(); rebuild_hysteria()
    es=time.strftime("%Y-%m-%d %H:%M",time.localtime(si['expires_at']))
    print(f"tg_id={tg_id} days={days} expires={es}")
    print(f"VLESS={vless}")
    print(f"Hysteria2={hy2}")

def cmd_trial(tg_id):
    if not can_request_trial(tg_id): print(f"❌ Trial used",file=sys.stderr); sys.exit(1)
    si=grant_subscription(tg_id,TRIAL_DAYS,"trial",is_trial=True)
    print(f"VLESS={build_vless_link(si['uuid'])}")
    print(f"Hysteria2={build_hysteria_link(si['hysteria_pass'])}")
    rebuild_xray(); rebuild_hysteria()
    print(f"tg_id={tg_id} trial={TRIAL_DAYS}d expires={time.strftime('%Y-%m-%d %H:%M',time.localtime(si['expires_at']))}")

def cmd_renew(tg_id, days=30):
    r=renew_subscription(tg_id,days)
    if not r: print(f"❌ No active subs",file=sys.stderr); sys.exit(1)
    rebuild_xray(); rebuild_hysteria()
    print(f"tg_id={tg_id} renewed={r['count']} keys +{days}d")

def cmd_list():
    with db() as conn:
        rows=conn.execute("SELECT s.tg_id,s.uuid,s.expires_at,s.active,s.is_trial FROM subscriptions s ORDER BY s.expires_at DESC").fetchall()
    for r in rows:
        s="active" if r["active"] and r["expires_at"]>int(time.time()) else "EXP"
        t="TRIAL" if r["is_trial"] else "PAID"
        print(f'{r["tg_id"]:>12} {r["uuid"][:8]}... {time.strftime("%Y-%m-%d",time.localtime(r["expires_at"]))} {s:>6} {t:>6}')

def cmd_remove(tg_id):
    with db() as conn: conn.execute("UPDATE subscriptions SET active=0 WHERE tg_id=? AND active=1",(tg_id,)); conn.commit()
    rebuild_xray(); rebuild_hysteria()
    print(f"✅ Keys deactivated for {tg_id}")

def main():
    p=argparse.ArgumentParser()
    sp=p.add_subparsers(dest="cmd",required=True)
    pg=sp.add_parser("grant"); pg.add_argument("tg_id",type=int); pg.add_argument("days",type=int); pg.add_argument("--note",default="")
    sp.add_parser("trial").add_argument("tg_id",type=int)
    pr=sp.add_parser("renew"); pr.add_argument("tg_id",type=int); pr.add_argument("--days",type=int,default=30)
    sp.add_parser("list")
    sp.add_parser("remove").add_argument("tg_id",type=int)
    a=p.parse_args()
    if not SERVER_IP: print("❌ SERVER_IP not set",file=sys.stderr); sys.exit(1)
    {"grant":lambda:cmd_grant(a.tg_id,a.days,a.note),"trial":lambda:cmd_trial(a.tg_id),"renew":lambda:cmd_renew(a.tg_id,a.days),"list":cmd_list,"remove":lambda:cmd_remove(a.tg_id)}[a.cmd]()

if __name__=="__main__": main()
