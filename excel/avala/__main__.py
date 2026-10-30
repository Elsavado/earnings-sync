"""python -m avala --sources learning,physical [--live]   (run from excel/)

Avala AI collection for the Workspace shared drive "Physical AI Data". Logs print counts only."""
import argparse
import os
import time
import traceback

from . import learning, physical
from .sink import Sink, State


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--sources", default="learning,physical")
    ap.add_argument("--out", default="out")
    ap.add_argument("--state", default="state/avala.json")
    ap.add_argument("--remote", default="ws:")
    ap.add_argument("--live", action="store_true")
    ap.add_argument("--budget-gb", type=float, default=40)
    ap.add_argument("--minutes", type=float, default=320)
    a = ap.parse_args()
    st = State(a.state)
    sink = Sink(a.out, a.remote, a.live, st, int(a.budget_gb * 2 ** 30), time.time() + a.minutes * 60)
    failed = []
    for name in [x.strip() for x in a.sources.split(",") if x.strip()]:
        t0 = time.time()
        try:
            if name == "learning":
                cookie = os.environ.get("AVALA_LEARN_COOKIE", "")
                n = learning.export(sink, st.section("learning"), cookie) if cookie else -1
                if not cookie:
                    print("learning: AVALA_LEARN_COOKIE not set, skipped")
            elif name == "physical":
                n = physical.collect(sink, st.section("physical"))
            else:
                print(f"{name}: unknown source")
                continue
            sink.flush()
            print(f"{name}: {n} items in {time.time() - t0:.0f}s; total {sink.files} files, {sink.sent / 2 ** 20:.0f} MB")
        except Exception:
            failed.append(name)
            print(f"{name}: FAILED")
            traceback.print_exc()
            try:
                sink.flush()
            except Exception:
                traceback.print_exc()
    print(f"done: {sink.files} files, {sink.sent / 2 ** 30:.2f} GB, live={a.live}")
    if failed:
        raise SystemExit(f"failed: {', '.join(failed)}")


if __name__ == "__main__":
    main()
