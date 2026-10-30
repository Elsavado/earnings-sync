"""Openly licensed physical-AI data of the kinds Avala works with (robot episodes, LiDAR / point clouds, driving
video, ROS bag / MCAP logs), from the Hugging Face Hub. Sorted by topic; each dataset in its own folder."""
import os
import time

import requests

from .sink import safe

ROOT = "Public Physical AI Data"
TOPICS = {  # folder: Hugging Face searches (task filter or free text)
    "Robot Manipulation (LeRobot)": ["author:lerobot", "task:robotics"],
    "Autonomous Driving": ["autonomous driving", "self-driving", "driving dataset", "dashcam"],
    "LiDAR & Point Clouds": ["lidar", "point cloud", "3d object detection", "pointcloud"],
    "Robot Logs (ROS bag & MCAP)": ["rosbag", "ros bag", "mcap", "ros2"],
    "Humanoids & Locomotion": ["humanoid", "locomotion", "legged robot"],
    "Drones & Aerial": ["drone", "uav", "aerial imagery"],
    "Video & Image Annotation": ["semantic segmentation driving", "bounding box annotation", "image segmentation dataset",
                                "video object tracking"],
    "Sensor Fusion & Calibration": ["sensor fusion", "camera calibration", "imu dataset", "radar dataset"],
}
OPEN = {"apache-2.0", "mit", "cc-by-4.0", "cc-by-sa-4.0", "cc0-1.0", "cc-by-3.0", "cc-by-sa-3.0", "odc-by", "odbl",
        "pddl", "bsd-3-clause", "bsd-2-clause", "bsd", "cdla-permissive-2.0", "cdla-permissive-1.0", "openrail",
        "cc-by-2.0", "unlicense", "gpl-3.0", "lgpl-3.0", "cc-by-nc-4.0", "cc-by-nc-sa-4.0"}
API = "https://huggingface.co/api/datasets"


def _hf(token):
    s = requests.Session()
    s.headers["User-Agent"] = "physical-ai-collector/1.0"
    if token:
        s.headers["Authorization"] = f"Bearer {token}"
    return s


def _list(s, query, offset_url=None):
    if offset_url:
        r = s.get(offset_url, timeout=60)
    elif query.startswith("author:"):
        r = s.get(API, params={"author": query[7:], "sort": "downloads", "limit": 50, "full": "true"}, timeout=60)
    elif query.startswith("task:"):
        r = s.get(API, params={"filter": f"task_categories:{query[5:]}", "sort": "downloads", "limit": 50,
                               "full": "true"}, timeout=60)
    else:
        r = s.get(API, params={"search": query, "sort": "downloads", "limit": 50, "full": "true"}, timeout=60)
    if r.status_code != 200:
        return [], None
    nxt = r.links.get("next", {}).get("url")
    return r.json(), nxt


def _license(d):
    card = d.get("cardData") or {}
    lic = card.get("license")
    if isinstance(lic, list):
        lic = lic[0] if lic else None
    if not lic:
        lic = next((t.split(":", 1)[1] for t in d.get("tags", []) if t.startswith("license:")), None)
    return (lic or "").lower()


def collect(sink, st, per_query=4, dataset_cap=6 * 2 ** 30):
    s = _hf(os.environ.get("HF_TOKEN"))
    seen = st.setdefault("hf_seen", [])
    seen_set = set(seen)
    cursor = st.setdefault("hf_cursor", {})
    partial = st.setdefault("hf_partial", {})  # dataset id -> [folder, search, files already sent]
    n = 0
    for rid, (folder, q, start) in list(partial.items()):
        if sink.full():
            return n
        n += _fetch(s, sink, st, rid, folder, q, start, dataset_cap)
    for folder, queries in TOPICS.items():
        for q in queries:
            if sink.full():
                return n
            items, nxt = _list(s, q, cursor.get(q))
            cursor[q] = nxt
            took = 0
            for d in items:
                if took >= per_query or sink.full():
                    break
                rid = d["id"]
                lic = _license(d)
                if rid in seen_set or d.get("gated") or d.get("private") or lic not in OPEN:
                    continue
                seen.append(rid)
                seen_set.add(rid)
                got = _fetch(s, sink, st, rid, folder, q, 0, dataset_cap, lic)
                took += got
                n += got
                time.sleep(1)
    return n


def _fetch(s, sink, st, rid, folder, q, start, cap, lic=None):
    """Download one dataset's files from index `start`; on the time/size budget, remember where it stopped."""
    partial = st.setdefault("hf_partial", {})
    r = s.get(f"{API}/{rid}/tree/main", params={"recursive": "true"}, timeout=120)
    files = [f for f in (r.json() if r.status_code == 200 else []) if f.get("type") == "file"
             and not f["path"].startswith(".") and not f["path"].endswith(".gitattributes")]
    files.sort(key=lambda f: f["path"])
    if not files or sum(int(f.get("size") or 0) for f in files) > cap:
        partial.pop(rid, None)
        return 0
    dest = f"{ROOT}/{folder}/{safe(rid.replace('/', ' - '), 100)}"
    for i in range(start, len(files)):
        if sink.full():
            partial[rid] = [folder, q, i]
            return 0
        name = files[i]["path"]
        sink.download(s, f"https://huggingface.co/datasets/{rid}/resolve/main/{name}", f"{dest}/{name}",
                      3 * 2 ** 30, headers=dict(s.headers))
    partial.pop(rid, None)
    cat = st.setdefault("catalog", {})
    cat[dest] = {"source": f"https://huggingface.co/datasets/{rid}", "license": lic or cat.get(dest, {}).get("license"),
                 "search": q}
    return 1
