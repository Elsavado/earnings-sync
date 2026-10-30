"""Staging folder -> Workspace shared drive with rclone move; JSON run state kept on the drive in _state/."""
import json
import os
import re
import shutil
import subprocess
import time


def safe(name, limit=120):
    name = re.sub(r'[\\/:*?"<>|\x00-\x1f]+', " ", str(name))
    name = re.sub(r"\s+", " ", name).strip(" .")
    return name[:limit].rstrip(" .") or "untitled"


class State:
    def __init__(self, path):
        self.path = path
        self.data = json.load(open(path, encoding="utf-8")) if os.path.exists(path) else {}

    def section(self, key):
        return self.data.setdefault(key, {})

    def save(self):
        os.makedirs(os.path.dirname(self.path) or ".", exist_ok=True)
        with open(self.path + ".tmp", "w", encoding="utf-8") as f:
            json.dump(self.data, f, indent=1, sort_keys=True)
        os.replace(self.path + ".tmp", self.path)


class Sink:
    def __init__(self, out, remote, live, state, budget_bytes, deadline):
        self.out, self.remote, self.live, self.state = out, remote, live, state
        self.budget, self.deadline = budget_bytes, deadline
        self.sent = self.pending = self.files = 0
        os.makedirs(out, exist_ok=True)

    def path(self, rel):
        p = os.path.join(self.out, *[safe(x, 150) for x in rel.split("/")])
        os.makedirs(os.path.dirname(p), exist_ok=True)
        return p

    def wrote(self, p):
        self.pending += os.path.getsize(p)
        self.files += 1
        if self.pending > 400 * 2 ** 20:
            self.flush()

    def full(self):
        return self.sent + self.pending >= self.budget or time.time() > self.deadline

    def download(self, http, url, rel, cap, headers=None):
        p = self.path(rel)
        n = 0
        try:
            with http.get(url, stream=True, timeout=180, headers=headers or {"User-Agent": "Mozilla/5.0"}) as r:
                if r.status_code != 200 or int(r.headers.get("Content-Length") or 0) > cap:
                    return False
                with open(p, "wb") as f:
                    for chunk in r.iter_content(1 << 20):
                        n += len(chunk)
                        if n > cap:
                            break
                        f.write(chunk)
        except Exception:
            n = 0
        if n == 0 or n > cap:
            if os.path.exists(p):
                os.remove(p)
            return False
        self.wrote(p)
        return True

    def flush(self):
        if self.live and os.listdir(self.out):
            subprocess.run(["rclone", "move", self.out, self.remote, "--transfers", "4", "--checkers", "8",
                            "--drive-chunk-size", "64M", "--retries", "5", "--low-level-retries", "20",
                            "--delete-empty-src-dirs", "-q"], check=True)
        elif not self.live:
            shutil.rmtree(self.out, ignore_errors=True)
        os.makedirs(self.out, exist_ok=True)
        self.state.save()
        if self.live:
            subprocess.run(["rclone", "copyto", self.state.path,
                            f"{self.remote}/_state/{os.path.basename(self.state.path)}", "-q"], check=True)
        self.sent += self.pending
        self.pending = 0
