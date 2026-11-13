"""Okta developer-org lab: real activity in the user's own Okta org, then an incremental export of its System Log.

Only touches users whose login starts with "lab." and groups/apps/zones named "Lab ...", so the admin account is
never changed. A steady pool of lab users "works" every run (sign-ins, failed sign-ins and lockouts, profile and group
changes, password resets, admin-role grants, app assignments, session revokes) plus joiner/leaver churn.

Env: OKTA_ORG_URL, OKTA_API_TOKEN, OUT (folder), ROUNDS (int), POOL (int), MODE (activity | export | both),
     STATE (path of a JSON file holding the end of the previous export; read and rewritten).
"""
import gzip
import json
import os
import random
import string
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

ORG = os.environ["OKTA_ORG_URL"].replace("﻿", "").strip().rstrip("/")
TOKEN = os.environ["OKTA_API_TOKEN"].replace("﻿", "").strip()
OUT = os.environ.get("OUT", "out")
ROUNDS = int(os.environ.get("ROUNDS", "20"))
POOL = int(os.environ.get("POOL", "50"))
MODE = os.environ.get("MODE", "both")
STATE = os.environ.get("STATE", "state.json")
DEPTS = ["Finance", "Engineering", "Sales", "HR", "IT", "Legal", "Operations"]
TITLES = ["Analyst", "Manager", "Engineer", "Director", "Associate", "Consultant", "Specialist"]
CITIES = ["New York", "Toronto", "Chicago", "Austin", "Seattle", "Boston", "Denver", "Vancouver"]
AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 14_6) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/18.0 Safari/605.1.15",
    "Mozilla/5.0 (iPhone; CPU iPhone OS 18_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Mobile Safari",
    "Mozilla/5.0 (Linux; Android 15) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0 Mobile Safari/537.36",
    "Mozilla/5.0 (X11; Linux x86_64; rv:132.0) Gecko/20100101 Firefox/132.0",
]
stats = {"calls": 0, "errors": 0}
AT_LIMIT = False


def call(method, path, body=None, auth=True, ua=None):
    url = path if path.startswith("http") else ORG + path
    data = json.dumps(body).encode() if body is not None else (b"" if method in ("POST", "PUT") else None)
    for _ in range(8):
        req = urllib.request.Request(url, data=data, method=method)
        req.add_header("Accept", "application/json")
        req.add_header("Content-Type", "application/json")
        req.add_header("User-Agent", ua or "okta-lab/1.0 (Linux) python")
        if auth:
            req.add_header("Authorization", "SSWS " + TOKEN)
        stats["calls"] += 1
        try:
            with urllib.request.urlopen(req, timeout=60) as r:
                raw = r.read()
                return r.status, (json.loads(raw) if raw else None), r.headers
        except urllib.error.HTTPError as e:
            raw = e.read()
            if e.code == 429:
                reset = int(e.headers.get("X-Rate-Limit-Reset", time.time() + 30))
                time.sleep(min(90, max(1, reset - time.time()) + 1))
                continue
            stats["errors"] += 1
            body_out = raw.decode(errors="replace")
            try:
                body_out = json.loads(raw)
            except ValueError:
                pass
            return e.code, body_out, e.headers
        except (urllib.error.URLError, TimeoutError, ConnectionError):
            time.sleep(5)
    return 429, None, {}


def pw():
    return "Lab!" + "".join(random.choices(string.ascii_letters + string.digits, k=14)) + "9a"


def find_or_create(kind, name, create):
    s, found, _ = call("GET", f"/api/v1/{kind}?q=" + urllib.parse.quote(name))
    key = (lambda x: x["profile"]["name"]) if kind == "groups" else (lambda x: x.get("label") or x.get("name"))
    obj = next((x for x in (found or []) if isinstance(x, dict) and key(x) == name), None)
    if not obj:
        s, obj, _ = call("POST", f"/api/v1/{kind}", create)
        if s not in (200, 201):
            print(f"could not create {kind} {name}: {s} {obj}")
            return None
    return obj


def new_user(login, dept, password):
    first = random.choice(["Alex", "Sam", "Jordan", "Taylor", "Casey", "Morgan", "Riley", "Jamie", "Avery", "Quinn"])
    s, u, _ = call("POST", "/api/v1/users?activate=true", {
        "profile": {"firstName": first, "lastName": "Lab", "email": login, "login": login, "department": dept,
                    "title": random.choice(TITLES), "city": random.choice(CITIES)},
        "credentials": {"password": {"value": password}}})
    return u if s in (200, 201) else None


def pool_users():
    users, url = [], "/api/v1/users?limit=200&search=" + urllib.parse.quote('profile.login sw "lab.pool."')
    while url:
        s, page, h = call("GET", url)
        if s != 200 or not page:
            break
        users += page
        nxt = [p for p in (h.get("Link") or "").split(",") if 'rel="next"' in p]
        url = nxt[0][nxt[0].find("<") + 1:nxt[0].find(">")] if nxt else None
    return users


def setup():
    groups = {}
    for d in DEPTS:
        g = find_or_create("groups", "Lab " + d, {"profile": {"name": "Lab " + d, "description": "Okta lab group"}})
        if g:
            groups[d] = g["id"]
    app = find_or_create("apps", "Lab Portal", {
        "name": "bookmark", "label": "Lab Portal", "signOnMode": "BOOKMARK",
        "settings": {"app": {"requestIntegration": False, "url": "https://example.com/lab-portal"}}})
    zone = find_or_create("zones", "Lab Office Zone", {
        "type": "IP", "name": "Lab Office Zone", "status": "ACTIVE",
        "gateways": [{"type": "CIDR", "value": "198.51.100.0/24"}], "proxies": None})
    # users Okta created but could not activate (free plan: ~10 active users) are removed again
    s, leftovers, _ = call("GET", "/api/v1/users?limit=200&search=" + urllib.parse.quote(
        'profile.login sw "lab." and (status eq "STAGED" or status eq "PROVISIONED" or status eq "DEPROVISIONED")'))
    for x in leftovers or []:
        if isinstance(x, dict):
            call("DELETE", f"/api/v1/users/{x['id']}")
            call("DELETE", f"/api/v1/users/{x['id']}")
    pool = [u for u in pool_users() if u.get("status") not in ("STAGED", "PROVISIONED", "DEPROVISIONED")]
    have = {u["profile"]["login"] for u in pool}
    for i in range(1, POOL + 1):
        login = f"lab.pool.{i:03d}@example.com"
        if login not in have:
            u = new_user(login, random.choice(DEPTS), pw())
            if u:
                pool.append(u)
                if u["profile"]["department"] in groups:
                    call("PUT", f"/api/v1/groups/{groups[u['profile']['department']]}/users/{u['id']}")
            else:
                print("pool stops at", len(pool), "users: the org's active-user limit is reached")
                s, x, _ = call("GET", "/api/v1/users/" + urllib.parse.quote(login))
                if s == 200:
                    call("DELETE", f"/api/v1/users/{x['id']}")
                    call("DELETE", f"/api/v1/users/{x['id']}")
                global AT_LIMIT
                AT_LIMIT = True
                break
    print(f"setup: {len(groups)} groups, app={'yes' if app else 'no'}, zone={'yes' if zone else 'no'}, pool={len(pool)}")
    return groups, app, zone, pool


def set_password(u):
    p = pw()
    s, _, _ = call("PUT", f"/api/v1/users/{u['id']}", {"profile": u["profile"], "credentials": {"password": {"value": p}}})
    return p if s == 200 else None


def sign_in(login, password, ua):
    return call("POST", "/api/v1/authn", {"username": login, "password": password}, auth=False, ua=ua)[0]


def workday(u, groups, app, zone):
    """One user's slice of activity; each action has its own chance so the mix varies."""
    uid, login, ua = u["id"], u["profile"]["login"], random.choice(AGENTS)
    s, cur, _ = call("GET", f"/api/v1/users/{uid}")
    if s != 200:
        return
    status = cur.get("status")
    if status == "SUSPENDED":
        call("POST", f"/api/v1/users/{uid}/lifecycle/unsuspend")
    if status == "LOCKED_OUT":
        call("POST", f"/api/v1/users/{uid}/lifecycle/unlock")
    p = set_password(cur) if status in ("ACTIVE", "PASSWORD_EXPIRED", "LOCKED_OUT", "SUSPENDED", "RECOVERY") else None
    r = random.random
    if p and r() < 0.8:
        sign_in(login, p, ua)                                    # normal sign-in
    if r() < 0.35:
        for _ in range(random.randint(1, 4)):                     # typos
            sign_in(login, "wrong-" + pw(), ua)
        if p:
            sign_in(login, p, ua)
    if r() < 0.06:
        for _ in range(12):                                       # brute force -> lockout
            sign_in(login, "guess-" + pw(), random.choice(AGENTS))
        call("POST", f"/api/v1/users/{uid}/lifecycle/unlock")
    if r() < 0.25:
        prof = dict(cur["profile"], title=random.choice(TITLES), city=random.choice(CITIES))
        call("POST", f"/api/v1/users/{uid}", {"profile": prof})
    if r() < 0.12 and groups:
        old = cur["profile"].get("department")
        new = random.choice([d for d in groups if d != old])
        if old in groups:
            call("DELETE", f"/api/v1/groups/{groups[old]}/users/{uid}")
        call("PUT", f"/api/v1/groups/{groups[new]}/users/{uid}")
        call("POST", f"/api/v1/users/{uid}", {"profile": dict(cur["profile"], department=new)})
    if r() < 0.1:
        call("POST", f"/api/v1/users/{uid}/lifecycle/reset_password?sendEmail=false")
    if r() < 0.08:
        call("POST", f"/api/v1/users/{uid}/lifecycle/expire_password?tempPassword=false")
    if r() < 0.1:
        call("DELETE", f"/api/v1/users/{uid}/sessions")
    if r() < 0.05:
        call("POST", f"/api/v1/users/{uid}/lifecycle/suspend")
    if r() < 0.04:                                                # temporary read-only admin, then revoke
        s, role, _ = call("POST", f"/api/v1/users/{uid}/roles", {"type": "READ_ONLY_ADMIN"})
        if s in (200, 201) and role:
            time.sleep(1)
            call("DELETE", f"/api/v1/users/{uid}/roles/{role['id']}")
    if app and r() < 0.12:
        if r() < 0.5:
            call("POST", f"/api/v1/apps/{app['id']}/users", {"id": uid})
        else:
            call("DELETE", f"/api/v1/apps/{app['id']}/users/{uid}")


def churn(groups):
    """Joiner/leaver: a contractor joins, signs in, gets moved, leaves."""
    login = f"lab.temp.{int(time.time() * 1000)}{random.randint(0, 99)}@example.com"
    d, p = random.choice(DEPTS), pw()
    u = new_user(login, d, p)
    if not u:
        return
    if d in groups:
        call("PUT", f"/api/v1/groups/{groups[d]}/users/{u['id']}")
    sign_in(login, p, random.choice(AGENTS))
    call("POST", f"/api/v1/users/{u['id']}/lifecycle/deactivate")
    call("DELETE", f"/api/v1/users/{u['id']}")


def activity():
    groups, app, zone, pool = setup()
    if not pool:
        print("no pool users; nothing to do")
        return
    for rnd in range(ROUNDS):
        for u in random.sample(pool, k=min(len(pool), random.randint(8, 20))):
            workday(u, groups, app, zone)
        for _ in range(0 if AT_LIMIT else random.randint(0, 2)):
            churn(groups)
        if zone and random.random() < 0.1:
            z = dict(zone, gateways=[{"type": "CIDR", "value": random.choice(["198.51.100.0/24", "203.0.113.0/24"])}])
            call("PUT", f"/api/v1/zones/{zone['id']}", z)
        print(f"round {rnd + 1}/{ROUNDS}: {stats['calls']} calls, {stats['errors']} refused")


def iso(t):
    return time.strftime("%Y-%m-%dT%H:%M:%S.000Z", time.gmtime(t))


def export():
    os.makedirs(OUT, exist_ok=True)
    state = {}
    if os.path.exists(STATE):
        with open(STATE, encoding="utf-8") as f:
            state = json.load(f)
    since = state.get("until") or iso(time.time() - 90 * 86400)
    until = iso(time.time() - 300)                                # 5-minute buffer: the log is written with a lag
    url = f"{ORG}/api/v1/logs?limit=1000&sortOrder=ASCENDING&since={since}&until={until}"
    name = f"okta_system_log_{since[:16].replace(':', '')}_{until[:16].replace(':', '')}.jsonl.gz"
    path, n, counts = os.path.join(OUT, name), 0, {}
    with gzip.open(path, "wt", encoding="utf-8") as f:
        while url:
            s, page, h = call("GET", url)
            if s != 200:
                print("log export failed", s, page)
                sys.exit(1)
            for ev in page or []:
                f.write(json.dumps(ev) + "\n")
                k = (ev.get("eventType"), (ev.get("outcome") or {}).get("result"))
                counts[k] = counts.get(k, 0) + 1
            n += len(page or [])
            nxt = [p for p in (h.get("Link") or "").split(",") if 'rel="next"' in p]
            nu = nxt[0][nxt[0].find("<") + 1:nxt[0].find(">")] if nxt else None
            url = nu if (nu and nu != url and page) else None
    with open(STATE, "w", encoding="utf-8") as f:
        json.dump({"until": until, "last_file": name, "last_events": n}, f)
    with open(os.path.join(OUT, name.replace(".jsonl.gz", ".counts.json")), "w", encoding="utf-8") as f:
        json.dump([[k[0], k[1], v] for k, v in sorted(counts.items(), key=lambda x: -x[1])], f)
    print(f"exported {n} System Log events ({since} -> {until}) to {path}")


if __name__ == "__main__":
    if MODE in ("activity", "both"):
        activity()
    if MODE in ("export", "both"):
        export()
