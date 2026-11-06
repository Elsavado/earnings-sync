"""One-off tidy of web-archive PDFs already on the drive (user 2026-11-06: "English version only", "no ESG reports
from USA companies"). Every PDF under the worldwide / Kenya & South Africa folders is read: not English -> deleted;
English -> the " (xx)" language tag leaves the name, and a US company's report moves to
"Company Sustainability Reports (USA)". The SEC folder "Company ESG Reports" becomes "Company ESG Reports (USA, SEC
filings)". Resumable: names already checked are kept in the state file. Logs print counts only.

    python -m finlitics.clean --remote ws:Financelitics --state state/finlitics-clean.json --minutes 320 [--live]
"""
import argparse
import concurrent.futures as cf
import json
import os
import re
import subprocess
import threading
import time

from . import common as C
from . import more as M

ESG = "08 ESG Reports & Data"
WORLD = f"{ESG}/Company Sustainability Reports (worldwide)"
USA = f"{ESG}/Company Sustainability Reports (USA)"


def rc(*args, capture=False):
    r = subprocess.run(["rclone", *args, "-q"], capture_output=True, timeout=900)
    return r.stdout if capture else r.returncode == 0


def text_of(body):
    import pymupdf
    try:
        doc = pymupdf.open(stream=body, filetype="pdf")
        t = "".join(doc[i].get_text() for i in range(min(doc.page_count, 12)))
        doc.close()
        return t
    except Exception:  # noqa: BLE001
        return ""


def folders(remote):
    """Folders written from the web archive: worldwide ESG, Kenya & South Africa ESG, the Kenya & South Africa
    sections of 07/09/10/11/13 and folder 14."""
    out = [WORLD, f"{ESG}/Company Sustainability Reports (Kenya & South Africa)",
           "14 Kenya & South Africa Annual & Integrated Reports"]
    for line in rc("lsf", remote, "--dirs-only", capture=True).decode().splitlines():
        top = line.rstrip("/")
        if top[:2] in ("07", "09", "10", "11", "13"):
            out.append(f"{top}/Kenya & South Africa")
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--remote", default="ws:Financelitics")
    ap.add_argument("--state", default="state/finlitics-clean.json")
    ap.add_argument("--minutes", type=float, default=320)
    ap.add_argument("--live", action="store_true")
    ap.add_argument("--threads", type=int, default=12)
    a = ap.parse_args()
    end = time.time() + a.minutes * 60
    st = json.load(open(a.state)) if os.path.exists(a.state) else {}
    done = set(st.get("done", []))
    lock = threading.Lock()
    stats = {"checked": 0, "deleted": 0, "renamed": 0, "to_usa": 0, "unreadable": 0}

    # US company names: the esgweb jobs' maps of site name -> made-up folder name, reversed
    us_keys = M._us_names()
    us_folders = set()
    for f in ("state/finlitics-esgweb_a.json", "state/finlitics-esgweb_b.json"):
        if os.path.exists(f):
            for label, made_up in json.load(open(f)).get("companies", {}).items():
                if label in us_keys:
                    us_folders.add(made_up)
    print(f"US company folders known: {len(us_folders)}")

    if a.live and not st.get("sec_moved"):
        if rc("lsf", f"{a.remote}/{ESG}/Company ESG Reports", "--max-depth", "1", capture=True):
            ok = rc("move", f"{a.remote}/{ESG}/Company ESG Reports",
                    f"{a.remote}/{ESG}/Company ESG Reports (USA, SEC filings)", "--drive-server-side-across-configs")
            print("SEC ESG folder renamed:", ok)
            st["sec_moved"] = ok
        else:
            st["sec_moved"] = True

    def one(path):
        if time.time() > end:
            return
        body = rc("cat", f"{a.remote}/{path}", capture=True)
        text = text_of(body) if body else None
        eng = None if text is None else C.is_english(text) and (not path.startswith(ESG) or C.is_esg(text))
        with lock:
            stats["checked"] += 1
        if eng is None:
            with lock:
                stats["unreadable"] += 1
            return
        if not eng:
            if not a.live or rc("deletefile", f"{a.remote}/{path}"):
                with lock:
                    stats["deleted"] += 1
                    done.add(path)
            return
        new = re.sub(r" \([a-z]{2,3}(?:-[A-Za-z]+)?\)(?= [0-9a-f]{6}\.pdf$)", "", path)
        parts = new.split("/")
        if new.startswith(WORLD + "/") and parts[2] in us_folders:
            new = f"{USA}/{'/'.join(parts[2:])}"
            with lock:
                stats["to_usa"] += 1
        if new != path:
            if a.live and not rc("moveto", f"{a.remote}/{path}", f"{a.remote}/{new}"):
                return
            with lock:
                stats["renamed"] += 1
        with lock:
            done.add(new)

    def save():
        with lock:
            st["done"] = sorted(done)
            st["stats"] = dict(stats)
        os.makedirs(os.path.dirname(a.state) or ".", exist_ok=True)
        json.dump(st, open(a.state, "w"))
        if a.live:
            rc("copyto", a.state, f"{a.remote}/_state/{os.path.basename(a.state)}")

    for folder in folders(a.remote):
        if time.time() > end:
            break
        listing = rc("lsf", "-R", f"{a.remote}/{folder}", "--files-only", "--fast-list", capture=True)
        todo = [f"{folder}/{p}" for p in listing.decode("utf-8", "replace").splitlines()
                if p.lower().endswith(".pdf") and f"{folder}/{p}" not in done]
        print(f"folder {folder[:2]}: {len(todo)} to check")
        with cf.ThreadPoolExecutor(a.threads) as ex:
            for i, _ in enumerate(ex.map(one, todo)):
                if i % 500 == 499:
                    save()
                    print(stats)
        save()
    print("final", stats)


if __name__ == "__main__":
    main()
