"""Learning library on shintiru@gmail.com (user 2026-11-07): shared Google Drive folders copied server side into
Library/<subject>/<course>, the design-pack disc images unpacked into browsable folders. The folder list (source
folder ids -> library paths) comes from the LIBRARY_MAP secret, so no link appears in this public repository.
Logs print counts only.

    python library/build.py --part drives|iso|isos-list  [--live]
"""
import argparse
import json
import os
import re
import shutil
import subprocess

DEST = "shintiru:Library"
SKIP = ["--exclude", "Thumbs.db", "--exclude", "desktop.ini", "--exclude", ".DS_Store"]
FAST = ["--drive-server-side-across-configs", "--transfers", "16", "--checkers", "16", "--tpslimit", "10",
        "--drive-skip-shortcuts", "--retries", "5", "--low-level-retries", "20", "-q"]

DS_GROUPS = [  # the data-science collection's 63 folders, by kind
    ("Universities & Courses", r"berkeley|columbia|duke|stanford|stony|wisconsin|crete|hildesheim|humburg|maryland|"
                               r"politecnico|mines|heig|helwan|eurocom|liris|ai6126|top courses|prestigious"),
    ("Cheat Sheets", r"cheat"),
    ("Books", r"books|mybooks|e-books"),
    ("Machine Learning & AI", r"deep learning|artificial|causal|computer vision|ml |mlops|machine learning|ethical"),
    ("Big Data & Cloud", r"big data|hadoop|spark|aws|google cloud|ibm"),
    ("Data Analysis & BI", r"data science|workshops|business intelligence|tableau|spss|probability|from where|leader"),
    ("Programming & Systems", r"python|scala|^os$|hardware"),
    ("Careers, Management & Research", r"management|chercheur|mba|thesis|ipen"),
    ("French-language Courses", r"french"),
]


def rc(*a, capture=False):
    r = subprocess.run(["rclone", *a], capture_output=True, text=True)
    return r.stdout if capture else r.returncode == 0


def src(fid, sub=""):
    return f"shintiru,root_folder_id={fid}:{sub}"


def drives(m, live):
    ok = bad = 0
    for e in m["folders"]:
        if e.get("group") == "ds":
            subs = [d.rstrip("/") for d in rc("lsf", src(e["id"]), "--dirs-only", capture=True).splitlines()]
            for d in subs:
                kind = next((g for g, rx in DS_GROUPS if re.search(rx, d.lower())), "Other")
                dst = f"{DEST}/{e['path']}/{kind}/{d.strip()}"
                ok_ = (not live) or rc("copy", src(e["id"], d), dst, *SKIP, *FAST)
                ok, bad = ok + ok_, bad + (not ok_)
            if live:  # loose files at the top of the collection
                rc("copy", src(e["id"]), f"{DEST}/{e['path']}/General", "--max-depth", "1", *SKIP, *FAST)
            continue
        for sub, dst in (e.get("subs") or {"": ""}).items():
            target = f"{DEST}/{e['path']}" + (f"/{dst}" if dst else "")
            excl = sum([["--exclude", x] for x in e.get("exclude", [])], [])
            if sub.endswith("|files"):  # only the files at that level
                sub, excl = sub[:-6], excl + ["--max-depth", "1"]
            ok_ = (not live) or rc("copy", src(e["id"], sub), target, *SKIP, *excl, *FAST)
            ok, bad = ok + ok_, bad + (not ok_)
    for f in m.get("files", []):  # single shared files
        ok_ = (not live) or rc("backend", "copyid", "shintiru:", f["id"], f"{DEST}/{f['path']}/",
                               "--drive-server-side-across-configs")
        ok, bad = ok + ok_, bad + (not ok_)
    print(f"drive folders copied: {ok}, failed: {bad}")
    return bad == 0


def isos(m, live, lane, lanes):
    """The print-pack disc images: each unpacked on the runner and uploaded as a folder of its designs."""
    iso = m["iso"]
    names = sorted(n for n in rc("lsf", src(iso["id"], iso["sub"]), "--files-only", capture=True).splitlines()
                   if n.lower().endswith(".iso"))
    work = "/mnt/iso"
    done = 0
    for i, name in enumerate(names):
        if i % lanes != lane:
            continue
        vol = re.sub(r"\.iso$", "", name, flags=re.I).strip()
        dst = f"{DEST}/{iso['path']}/{vol}"
        if rc("lsf", dst, "--max-depth", "1", capture=True).strip():
            continue  # unpacked in an earlier run
        if not live:
            continue
        shutil.rmtree(work, ignore_errors=True)
        os.makedirs(work)
        if not rc("copy", src(iso["id"], f"{iso['sub']}/{name}"), work, "-q"):
            continue
        subprocess.run(["7z", "x", "-y", f"-o{work}/out", f"{work}/{name}"], capture_output=True)
        os.remove(f"{work}/{name}")
        if rc("copy", f"{work}/out", dst, *SKIP, "--transfers", "8", "-q"):
            done += 1
    shutil.rmtree(work, ignore_errors=True)
    print(f"disc images unpacked: {done} of {len(names)} (lane {lane}/{lanes})")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--part", required=True)
    ap.add_argument("--lane", default="0/1")
    ap.add_argument("--live", action="store_true")
    a = ap.parse_args()
    m = json.loads(os.environ["LIBRARY_MAP"])
    if a.part == "drives":
        drives(m, a.live)
    else:
        k, n = (int(x) for x in a.lane.split("/"))
        isos(m, a.live, k, n)
    if a.live:
        print("library:", rc("size", DEST, "--json", "-q", capture=True).strip())


if __name__ == "__main__":
    main()
