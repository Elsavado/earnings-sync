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
    ap.add_argument("--mode", default="esg", choices=("esg", "repair"))
    ap.add_argument("--lane", default="0/1", help="k/n: this job's share of the files (repair mode)")
    a = ap.parse_args()
    if a.mode == "repair":
        return repair(a)
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


# ---------------------------------------------------------------- repair (2026-11-06: PDFs that show web-page code)

REPAIR_SKIP = ("06 ", "12 ", "_state")


def rebuild_html(text):
    """The page code a bad PDF printed, joined back into one web page: a line that ends in '-' was split at that
    hyphen, every other line break was a space."""
    out = []
    for line in text.splitlines():
        if out and out[-1].endswith("-"):
            out[-1] += line
        else:
            out.append(line)
    return " ".join(out)


TAG = re.compile(r"<\s*/?\s*(p|div|font|td|tr|table|span|br|html|body)[\s>]|&nbsp;|style\s*=", re.I)
XBRL = re.compile(r"(fasb\.org|xbrl\.org|sec\.gov/|us-gaap|dei:|srt:|ifrs-full|http://)|^\S{40,}$", re.I)


def blank_xbrl(d, pdf):
    """Covers the words of the hidden XBRL block (taxonomy links, run-together codes) on the first pages with white
    boxes and removes their text, then checks that the pages read as a document."""
    import pymupdf
    for i in range(min(4, d.page_count)):
        pg = d[i]
        for w in pg.get_text("words"):
            if XBRL.search(w[4]):
                pg.add_redact_annot(pymupdf.Rect(w[:4]), fill=(1, 1, 1))
        pg.apply_redactions(images=pymupdf.PDF_REDACT_IMAGE_NONE)
    first = "".join(d[i].get_text() for i in range(min(4, d.page_count)))
    if C.looks_like_code(first):
        return False
    d.save(pdf, garbage=3, deflate=True)
    return True


def repair(a):
    """Every PDF / .htm outside 06 and 12: a PDF whose pages are web-page code is rebuilt from that code and printed
    again in a browser (same name, replaced in place); a .htm becomes a PDF; LibreOffice lock / temp files go."""
    import hashlib
    import shutil
    import tempfile
    import pymupdf
    k, n = (int(x) for x in a.lane.split("/"))
    end = time.time() + a.minutes * 60
    st = json.load(open(a.state)) if os.path.exists(a.state) else {}
    done = set(st.get("done", []))
    lock = threading.Lock()
    stats = {"checked": 0, "fine": 0, "repaired": 0, "htm_converted": 0, "junk_deleted": 0, "failed": 0}
    listing = rc("lsf", "-R", a.remote, "--files-only", "--fast-list", "--exclude", "_state/**", capture=True)
    paths = [p for p in listing.decode("utf-8", "replace").splitlines() if not p.startswith(REPAIR_SKIP)]
    mine = [p for p in paths if int(hashlib.md5(p.encode()).hexdigest(), 16) % n == k and p not in done]
    junk = [p for p in mine if os.path.basename(p).startswith(".~lock.") or p.endswith(".tmp")]
    todo = [p for p in mine if p.lower().endswith((".pdf", ".htm", ".html")) and p not in junk]
    print(f"lane {a.lane}: {len(todo)} files to check, {len(junk)} leftover lock/temp files")

    def bump(key):
        with lock:
            stats[key] += 1

    for p in junk:
        if a.live and rc("deletefile", f"{a.remote}/{p}"):
            bump("junk_deleted")

    def one(path):
        if time.time() > end:
            return
        tmp = tempfile.mkdtemp(prefix="rep_")
        try:
            body = rc("cat", f"{a.remote}/{path}", capture=True)
            bump("checked")
            if not body:
                bump("failed")
                return
            if path.lower().endswith((".htm", ".html")):
                src, kind = os.path.join(tmp, "doc.html"), "htm_converted"
                open(src, "wb").write(body)
            else:
                try:
                    d = pymupdf.open(stream=body, filetype="pdf")
                    first = "".join(d[i].get_text() for i in range(min(4, d.page_count)))
                    if not C.looks_like_code(first):
                        d.close()
                        bump("fine")
                        with lock:
                            done.add(path)
                        return
                    kind = "repaired"
                    if not TAG.search(first):  # a readable filing with its hidden XBRL block printed first
                        src, pdf = None, os.path.join(tmp, "doc.pdf")
                        ok = blank_xbrl(d, pdf)
                        d.close()
                        if not ok:
                            bump("failed")
                            return
                    else:
                        text = "\n".join(pg.get_text() for pg in d)
                        d.close()
                        src = os.path.join(tmp, "doc.html")
                        open(src, "w", encoding="utf-8").write(rebuild_html(text))
                except Exception:  # noqa: BLE001
                    bump("failed")
                    return
            if src:
                pdf = os.path.join(tmp, "doc.pdf")
                if not C.html_to_pdf(src, pdf):
                    bump("failed")
                    return
            new = re.sub(r"\.html?$", ".pdf", path, flags=re.I)
            if a.live:
                if not rc("copyto", pdf, f"{a.remote}/{new}"):
                    bump("failed")
                    return
                if new != path:
                    rc("deletefile", f"{a.remote}/{path}")
            bump(kind)
            with lock:
                done.add(new)
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    def save():
        with lock:
            st["done"] = sorted(done)
            st["stats"] = dict(stats)
        os.makedirs(os.path.dirname(a.state) or ".", exist_ok=True)
        json.dump(st, open(a.state, "w"))
        if a.live:
            rc("copyto", a.state, f"{a.remote}/_state/{os.path.basename(a.state)}")

    with cf.ThreadPoolExecutor(a.threads) as ex:
        for i, _ in enumerate(ex.map(one, todo)):
            if i % 300 == 299:
                save()
                print(stats)
    save()
    print("final", stats)


if __name__ == "__main__":
    main()
