"""Shintiru library, phase 2 (user 2026-11-07 list, sent 2026-11-10): the free learning websites.

  08 Open Learning Resources/
     TVET CDACC (Kenya)/                 curricula, policies, learning guides (downloads page)
     Kenya School of TVET/               downloadable resources page
     Open Textbook Library/<subject>/    free textbooks (open.umn.edu data feed); a book that is only a web page or
                                         a publisher shop is listed in "00 Online-only textbooks.csv" instead
     OpenLearn (Open University)/        free courses' PDF downloads (best effort: the site limits automated tools)
     MIT 6.042J Mathematics for Computer Science/   the whole OCW course package, unpacked
  09 Literature & eBooks/Planet eBook Classics/      the free classic novels (PDF + EPUB)

Files already in the library are skipped, so every run resumes. Public repository: counts only in the log.
"""
import argparse, csv, io, os, re, shutil, subprocess, sys, tempfile, time, urllib.parse, zipfile
import requests

DEST = "shintiru:Library"
OLR = f"{DEST}/08 Open Learning Resources"
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130 Safari/537.36"
S = requests.Session()
S.headers["User-Agent"] = UA
T0 = time.time()
MAX_BYTES = 400 * 2 ** 20


def left(minutes):
    return minutes * 60 - (time.time() - T0)


def get(url, **kw):
    for a in range(3):
        try:
            r = S.get(url, timeout=kw.pop("timeout", 90), **kw)
            if r.status_code == 200:
                return r
            if r.status_code in (403, 404, 410):
                return None
        except requests.RequestException:
            pass
        time.sleep(3 * (a + 1))
    return None


def clean(name, n=150):
    name = re.sub(r'[\\/:*?"<>|\x00-\x1f]+', " ", urllib.parse.unquote(name))
    return re.sub(r"\s+", " ", name).strip(" .")[:n] or "untitled"


def have(path):
    r = subprocess.run(["rclone", "lsf", path, "-R", "--files-only", "--fast-list"], capture_output=True, text=True)
    return set(r.stdout.splitlines())


def fetch(url, path, want_pdf=False):
    """download one file -> True; a web page is refused when a file was expected"""
    try:
        with S.get(url, timeout=180, stream=True) as r:
            if r.status_code != 200:
                return False
            ct = r.headers.get("content-type", "").lower()
            if "text/html" in ct or (want_pdf and "pdf" not in ct and not url.lower().endswith(".pdf")):
                return False
            os.makedirs(os.path.dirname(path), exist_ok=True)
            n = 0
            with open(path, "wb") as f:
                for chunk in r.iter_content(1 << 16):
                    n += len(chunk)
                    if n > MAX_BYTES:
                        break
                    f.write(chunk)
            if n > MAX_BYTES or n < 1000:
                os.remove(path)
                return False
            return True
    except requests.RequestException:
        return False


def push(local, dest):
    return subprocess.run(["rclone", "copy", local, dest, "--transfers", "8", "-q"]).returncode == 0


def page_files(url, exts=("pdf", "docx", "doc", "xlsx", "xls", "pptx", "zip", "epub")):
    r = get(url)
    if not r:
        return []
    links = re.findall(r'href="([^"]+\.(?:%s))"' % "|".join(exts), r.text, re.I)
    return list(dict.fromkeys(urllib.parse.urljoin(url, html_unescape(x)) for x in links))


def html_unescape(s):
    import html
    return html.unescape(s)


def simple(url, dest, label):
    """a downloads page: every document on it"""
    work = tempfile.mkdtemp()
    done = have(dest)
    got = 0
    for u in page_files(url):
        name = clean(u.rsplit("/", 1)[-1])
        if name in done:
            continue
        if fetch(u, os.path.join(work, name)):
            got += 1
    if got:
        push(work, dest)
    shutil.rmtree(work, ignore_errors=True)
    print(f"{label}: {got} new files ({len(done)} already there)", flush=True)


def textbooks(minutes):
    dest = f"{OLR}/Open Textbook Library"
    done = {os.path.basename(x) for x in have(dest)}
    work = tempfile.mkdtemp()
    rows, got, page, total = [], 0, 1, 0
    while left(minutes) > 900:
        r = get(f"https://open.umn.edu/opentextbooks/textbooks.json?page={page}")
        if not r:
            break
        d = r.json()
        for b in d.get("data", []):
            if b.get("language") not in (None, "eng"):
                continue
            total += 1
            subj = clean((b.get("subjects") or [{}])[0].get("name") or "General", 60)
            title = clean(b["title"] + (f" ({b['edition_statement']})" if b.get("edition_statement") else ""), 140)
            fname = title + ".pdf"
            if fname in done:
                continue
            pdfs = [f["url"] for f in b.get("formats", []) if (f.get("type") or "").upper() == "PDF" and f.get("url")]
            ok = False
            for u in pdfs:
                if fetch(u, os.path.join(work, subj, fname), want_pdf=True):
                    ok = True
                    break
                # a landing page: its first PDF link
                for v in page_files(u, ("pdf",))[:3]:
                    if fetch(v, os.path.join(work, subj, fname), want_pdf=True):
                        ok = True
                        break
                if ok:
                    break
            if ok:
                got += 1
                done.add(fname)
            else:
                rows.append({"title": title, "subject": subj, "license": b.get("license") or "",
                             "read online": (b.get("formats") or [{}])[0].get("url", "") or b.get("url", ""),
                             "catalogue page": b.get("url") or ""})
        if got and got % 50 == 0 or not d.get("links", {}).get("next"):
            push(work, dest)
            shutil.rmtree(work, ignore_errors=True)
            os.makedirs(work, exist_ok=True)
        if not d.get("links", {}).get("next"):
            break
        page += 1
    push(work, dest)
    if rows:
        p = os.path.join(tempfile.gettempdir(), "00 Online-only textbooks.csv")
        old = subprocess.run(["rclone", "cat", f"{dest}/00 Online-only textbooks.csv"], capture_output=True,
                             text=True, encoding="utf-8").stdout
        prev = {x["title"]: x for x in csv.DictReader(io.StringIO(old))} if old.strip() else {}
        prev.update({x["title"]: x for x in rows})
        prev = {k: v for k, v in prev.items() if k + ".pdf" not in done}
        with open(p, "w", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=["title", "subject", "license", "read online", "catalogue page"])
            w.writeheader()
            w.writerows(sorted(prev.values(), key=lambda x: (x["subject"], x["title"])))
        subprocess.run(["rclone", "copyto", p, f"{dest}/00 Online-only textbooks.csv", "-q"])
    shutil.rmtree(work, ignore_errors=True)
    print(f"Open Textbook Library: {got} new PDFs this run; {total} English books seen up to page {page}; "
          f"{len(rows)} online-only/unavailable listed", flush=True)


def planet():
    dest = f"{DEST}/09 Literature & eBooks/Planet eBook Classics"
    done = {os.path.basename(x) for x in have(dest)}
    work = tempfile.mkdtemp()
    sm = get("https://www.planetebook.com/post-sitemap.xml")
    posts = re.findall(r"<loc><!\[CDATA\[(https://www\.planetebook\.com/[a-z0-9-]+/)\]\]></loc>", sm.text) if sm else []
    got = 0
    for p in posts:
        r = get(p)
        if not r:
            continue
        files = list(dict.fromkeys(re.findall(r'href="(/free-ebooks/[^"]+\.(?:pdf|epub))"', r.text)))
        if not files:
            continue
        m = re.search(r"<h1[^>]*>(.*?)</h1>", r.text, re.S)
        title = clean(re.sub(r"<[^>]+>", " ", m.group(1)) if m else p.rstrip("/").rsplit("/", 1)[-1], 120)
        for f in files:
            name = f"{title}.{f.rsplit('.', 1)[-1]}"
            if name not in done and fetch("https://www.planetebook.com" + f, os.path.join(work, name)):
                got += 1
    push(work, dest)
    shutil.rmtree(work, ignore_errors=True)
    print(f"Planet eBook: {got} new files from {len(posts)} pages ({len(done)} already there)", flush=True)


def mit():
    dest = f"{OLR}/MIT 6.042J Mathematics for Computer Science"
    if have(dest):
        print("MIT 6.042J: already there", flush=True)
        return
    work = tempfile.mkdtemp()
    z = os.path.join(work, "c.zip")
    u = "https://ocw.mit.edu/courses/6-042j-mathematics-for-computer-science-spring-2015/6.042j-spring-2015.zip"
    global MAX_BYTES
    MAX_BYTES, keep = 6 * 2 ** 30, MAX_BYTES
    ok = fetch(u, z)
    MAX_BYTES = keep
    if ok:
        with zipfile.ZipFile(z) as zf:
            zf.extractall(os.path.join(work, "out"))
        os.remove(z)
        push(os.path.join(work, "out"), dest)
    shutil.rmtree(work, ignore_errors=True)
    print(f"MIT 6.042J: {'unpacked' if ok else 'download failed'}", flush=True)


def openlearn(minutes):
    dest = f"{OLR}/OpenLearn (Open University)"
    done = {os.path.basename(x) for x in have(dest)}
    cat = get("https://www.open.edu/openlearn/free-courses/full-catalogue")
    if not cat:
        print("OpenLearn: catalogue refused (the site blocks automated tools)", flush=True)
        return
    courses = list(dict.fromkeys(re.findall(r'href="(https://www\.open\.edu/openlearn/[a-z0-9-]+/[a-z0-9-]+/?)"',
                                            cat.text)))
    work = tempfile.mkdtemp()
    got = 0
    for c in courses:
        if left(minutes) < 900:
            break
        title = clean(c.rstrip("/").rsplit("/", 1)[-1].replace("-", " ").title(), 120)
        if f"{title}.pdf" in done:
            continue
        r = get(c.rstrip("/") + "/content-section-0")
        if not r:
            continue
        pdf = re.search(r'href="([^"]+)"[^>]*>[^<]*(?:PDF|pdf)', r.text) or re.search(
            r'href="([^"]+targetdoc=[^"]+)"[^>]*>\s*PDF', r.text)
        if pdf and fetch(urllib.parse.urljoin(c, html_unescape(pdf.group(1))), os.path.join(work, f"{title}.pdf"),
                         want_pdf=True):
            got += 1
        time.sleep(1)
        if got and got % 50 == 0:
            push(work, dest)
            shutil.rmtree(work, ignore_errors=True)
            os.makedirs(work, exist_ok=True)
    push(work, dest)
    shutil.rmtree(work, ignore_errors=True)
    print(f"OpenLearn: {got} new course PDFs from {len(courses)} catalogue links", flush=True)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--minutes", type=int, default=320)
    a = ap.parse_args()
    simple("https://www.tvetcdacc.go.ke/downloads/", f"{OLR}/TVET CDACC (Kenya)", "TVET CDACC")
    simple("https://kstvet.ac.ke/downloadable-resources/", f"{OLR}/Kenya School of TVET", "Kenya School of TVET")
    planet()
    mit()
    openlearn(a.minutes // 3)
    textbooks(a.minutes)


if __name__ == "__main__":
    sys.exit(main())
