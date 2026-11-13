"""Okta developer-org lab: real activity in the user's own Okta org, then export of its System Log.

Only touches users whose login starts with "lab." and groups named "Lab *", so the admin account is never changed.
Env: OKTA_ORG_URL (https://dev-123456.okta.com), OKTA_API_TOKEN (SSWS token), OUT (folder), ROUNDS (int), MODE.
MODE: activity | export | both.
"""
import json
import os
import random
import string
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

ORG = os.environ["OKTA_ORG_URL"].rstrip("/")
TOKEN = os.environ["OKTA_API_TOKEN"]
OUT = os.environ.get("OUT", "out")
ROUNDS = int(os.environ.get("ROUNDS", "3"))
MODE = os.environ.get("MODE", "both")
DEPTS = ["Finance", "Engineering", "Sales", "HR", "IT"]


def call(method, path, body=None, auth=True, ok=(200, 201, 204)):
    url = path if path.startswith("http") else ORG + path
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(url, data=data, method=method)
    req.add_header("Accept", "application/json")
    req.add_header("Content-Type", "application/json")
    if auth:
        req.add_header("Authorization", "SSWS " + TOKEN)
    for attempt in range(5):
        try:
            with urllib.request.urlopen(req, timeout=60) as r:
                raw = r.read()
                return r.status, (json.loads(raw) if raw else None), r.headers
        except urllib.error.HTTPError as e:
            if e.code == 429:
                reset = int(e.headers.get("X-Rate-Limit-Reset", time.time() + 30))
                time.sleep(max(1, reset - time.time()) + 1)
                continue
            raw = e.read()
            if e.code in ok:
                return e.code, None, e.headers
            return e.code, (json.loads(raw) if raw[:1] in (b"{", b"[") else raw.decode(errors="replace")), e.headers
    return 429, None, {}


def pw():
    return "Lab!" + "".join(random.choices(string.ascii_letters + string.digits, k=14)) + "9a"


def activity():
    groups = {}
    for d in DEPTS:
        name = "Lab " + d
        s, found, _ = call("GET", "/api/v1/groups?q=" + urllib.parse.quote(name))
        g = next((x for x in (found or []) if x["profile"]["name"] == name), None)
        if not g:
            s, g, _ = call("POST", "/api/v1/groups", {"profile": {"name": name, "description": "Okta lab group"}})
        groups[d] = g["id"]
    for rnd in range(ROUNDS):
        users = []
        for i in range(4):
            tag = f"{int(time.time())}{rnd}{i}"
            d = random.choice(DEPTS)
            p = pw()
            s, u, _ = call("POST", "/api/v1/users?activate=true", {
                "profile": {"firstName": "Lab", "lastName": f"User{tag}", "email": f"lab.{tag}@example.com",
                            "login": f"lab.{tag}@example.com", "department": d},
                "credentials": {"password": {"value": p}}})
            if s not in (200, 201):
                print("create user failed", s, u); continue
            users.append((u, p, d))
            call("PUT", f"/api/v1/groups/{groups[d]}/users/{u['id']}")
            print("user", u["profile"]["login"], d)
        for u, p, d in users:
            login = u["profile"]["login"]
            # sign-ins: good password, then wrong passwords (failed logins, possible lockout)
            call("POST", "/api/v1/authn", {"username": login, "password": p}, auth=False)
            for _ in range(random.randint(1, 6)):
                call("POST", "/api/v1/authn", {"username": login, "password": "wrong-" + pw()}, auth=False)
            call("POST", f"/api/v1/users/{u['id']}/lifecycle/unlock")
            call("POST", f"/api/v1/users/{u['id']}", {"profile": {"title": random.choice(["Analyst", "Manager", "Engineer"])}})
            call("POST", f"/api/v1/users/{u['id']}/lifecycle/expire_password?tempPassword=false")
            call("POST", f"/api/v1/users/{u['id']}/lifecycle/suspend")
            call("POST", f"/api/v1/users/{u['id']}/lifecycle/unsuspend")
            nd = random.choice([x for x in DEPTS if x != d])
            call("DELETE", f"/api/v1/groups/{groups[d]}/users/{u['id']}")
            call("PUT", f"/api/v1/groups/{groups[nd]}/users/{u['id']}")
        # offboard: deactivate then delete (two calls, as Okta requires)
        for u, _, _ in users:
            call("POST", f"/api/v1/users/{u['id']}/lifecycle/deactivate")
            call("DELETE", f"/api/v1/users/{u['id']}")
        time.sleep(5)


def export():
    os.makedirs(OUT, exist_ok=True)
    since = time.strftime("%Y-%m-%dT%H:%M:%S.000Z", time.gmtime(time.time() - 90 * 86400))
    url = f"{ORG}/api/v1/logs?limit=1000&sortOrder=ASCENDING&since={since}"
    n = 0
    path = os.path.join(OUT, "okta_system_log.jsonl")
    with open(path, "w", encoding="utf-8") as f:
        while url:
            s, page, h = call("GET", url)
            if s != 200:
                print("log export failed", s, page); sys.exit(1)
            if not page:
                break
            for ev in page:
                f.write(json.dumps(ev) + "\n")
            n += len(page)
            nxt = None
            for part in (h.get("Link") or "").split(","):
                if 'rel="next"' in part:
                    nxt = part[part.find("<") + 1:part.find(">")]
            url = nxt if nxt and nxt != url else None
    print(f"exported {n} System Log events to {path}")


if __name__ == "__main__":
    if MODE in ("activity", "both"):
        activity()
        time.sleep(30)  # let the System Log catch up
    if MODE in ("export", "both"):
        export()
