"""user 2026-11-10: dates are no longer shifted. Put the unredacted LAW 2 originals back from the shared-drive trash
(only what was trashed since the redaction began), then delete the date-shifted 'Case XXXXXX' copies so the redact
lanes can do them again. Prints counts only."""
import json, re, subprocess, sys, time
from concurrent.futures import ThreadPoolExecutor
import requests

D = "0AM6PzKRbJBK-Uk9PVA"
R = "ws:"
CUT = "2026-11-09T17:00:00"
S = requests.Session()
H = {}


def refresh():
    subprocess.run(["rclone", "lsf", R, "--max-depth", "1"], capture_output=True)
    cfg = json.loads(subprocess.run(["rclone", "config", "dump"], capture_output=True, text=True).stdout)
    H["Authorization"] = "Bearer " + json.loads(cfg["ws"]["token"])["access_token"]


def lsjson(path, *a):
    return json.loads(subprocess.run(["rclone", "lsjson", R + path, "--dirs-only", *a], capture_output=True, text=True,
                                     encoding="utf-8").stdout or "[]")


def untrash():
    refresh()
    law2 = [x for x in lsjson("") if x["Name"] == "LAW 2"][0]["ID"]
    ok = {law2} | {x["ID"] for x in lsjson("LAW 2", "-R", "--fast-list")}
    items, tok = [], None
    while True:
        p = {"q": "trashed=true", "corpora": "drive", "driveId": D, "includeItemsFromAllDrives": True,
             "supportsAllDrives": True, "pageSize": 1000,
             "fields": "nextPageToken,files(id,parents,mimeType,trashedTime)"}
        if tok:
            p["pageToken"] = tok
        r = S.get("https://www.googleapis.com/drive/v3/files", headers=H, params=p).json()
        items += r.get("files", [])
        tok = r.get("nextPageToken")
        if not tok:
            break
    items = [i for i in items if i.get("trashedTime", "") >= CUT]
    folders = {i["id"] for i in items if i["mimeType"].endswith("folder")}
    grew = True
    while grew:
        grew = False
        for i in items:
            if i["id"] in folders and i["id"] not in ok and any(p in ok for p in i.get("parents", [])):
                ok.add(i["id"])
                grew = True
    pick = [i for i in items if any(p in ok for p in i.get("parents", []))]
    print(f"trashed since cutoff: {len(items)}; under LAW 2: {len(pick)}", flush=True)

    def one(i):
        for a in range(7):
            r = S.patch(f"https://www.googleapis.com/drive/v3/files/{i['id']}", headers=H,
                        params={"supportsAllDrives": True}, json={"trashed": False})
            if r.status_code == 200:
                return 1
            if r.status_code == 401:
                refresh()
            time.sleep(2 ** a)
        return 0

    fs = [i for i in pick if i["id"] in folders]
    with ThreadPoolExecutor(8) as ex:
        print("folders restored:", sum(ex.map(one, fs)), "of", len(fs), flush=True)
    rest, done = [i for i in pick if i["id"] not in folders], 0
    with ThreadPoolExecutor(16) as ex:
        for k, v in enumerate(ex.map(one, rest)):
            done += v
            if k % 2000 == 0:
                print(f"  {k}: {done} restored", flush=True)
            if k % 20000 == 19999:
                refresh()
    print("files restored:", done, "of", len(rest), flush=True)
    return done == len(rest)


def drop_shifted():
    dirs = [x["Path"] for x in lsjson("LAW 2", "-R", "--fast-list") if re.fullmatch(r"Case [0-9A-F]{6}", x["Name"])]
    print("date-shifted case folders:", len(dirs), flush=True)

    def purge(d):
        return subprocess.run(["rclone", "purge", f"{R}LAW 2/{d}", "-q"]).returncode == 0

    with ThreadPoolExecutor(8) as ex:
        print("removed:", sum(ex.map(purge, dirs)), flush=True)
    subprocess.run(["rclone", "rmdirs", R + "LAW 2", "--leave-root", "-q"])


if __name__ == "__main__":
    full = untrash()
    if not full:
        print("some files not restored - case folders left in place; run again")
        sys.exit(1)
    drop_shifted()
