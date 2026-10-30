"""Avala Learning (learning.avala.ai) export for the signed-in account.

Each module becomes one Word file (lessons -> steps: text, images, quiz choices with the account's own answer,
practice examples), plus its training videos as MP4. Grouped by learning journey; modules outside any journey
are grouped by their industry tag."""
import ast
import base64
import io
import json
import os
import re
import time

import requests
from docx import Document
from docx.shared import Inches, Pt
from PIL import Image

from .sink import safe

BASE = "https://learning.avala.ai"
ROOT = "Avala Learning"


def session(cookie):
    s = requests.Session()
    s.headers["User-Agent"] = "Mozilla/5.0 (Avala Learning export for the account holder)"
    s.headers["Cookie"] = cookie
    return s


def _get(s, url, **kw):
    for i in range(4):
        try:
            r = s.get(url, timeout=120, **kw)
            if r.status_code == 200:
                return r
            if r.status_code in (401, 403, 404):
                return r
        except requests.RequestException:
            pass
        time.sleep(5 * 2 ** i)
    return None


def _image(s, src):
    """Bytes of an image as PNG/JPEG that python-docx can embed, or None."""
    try:
        if src.startswith("data:image"):
            raw = base64.b64decode(src.split(",", 1)[1])
        else:
            r = s.get(src, timeout=60, headers={"Cookie": ""})
            if r.status_code != 200:
                return None
            raw = r.content
        im = Image.open(io.BytesIO(raw))
        if im.format in ("PNG", "JPEG") and not getattr(im, "is_animated", False):
            return raw
        out = io.BytesIO()
        im.convert("RGBA" if im.mode in ("RGBA", "LA", "P") else "RGB").save(out, "PNG")
        return out.getvalue()
    except Exception:
        return None


INLINE = re.compile(r"(\*\*[^*]+\*\*|\*[^*]+\*|`[^`]+`|\[[^\]]+\]\([^)]+\))")


def _runs(p, text):
    for part in INLINE.split(text):
        if not part:
            continue
        if part.startswith("**") and part.endswith("**"):
            p.add_run(part[2:-2]).bold = True
        elif part.startswith("`") and part.endswith("`"):
            r = p.add_run(part[1:-1])
            r.font.name = "Consolas"
        elif part.startswith("[") and "](" in part:
            label, url = part[1:-1].split("](", 1)
            p.add_run(label)
            if not url.startswith("#"):
                p.add_run(f" ({url})").italic = True
        elif part.startswith("*") and part.endswith("*") and len(part) > 2:
            p.add_run(part[1:-1]).italic = True
        else:
            p.add_run(part)


IMG = re.compile(r"!\[([^\]]*)\]\(([^)\s]+)[^)]*\)")
VIDEO = re.compile(r"https://player\.vimeo\.com/[^\s\"')\]]+")


def markdown(d, s, md, videos):
    """Small Markdown renderer: headings, lists, tables, images, video references."""
    table = []

    def flush_table():
        rows = [r for r in table if not re.fullmatch(r"\|?\s*:?-{2,}.*", r)]
        if rows:
            cells = [[c.strip() for c in r.strip().strip("|").split("|")] for r in rows]
            t = d.add_table(rows=0, cols=max(len(c) for c in cells))
            t.style = "Light Grid Accent 1"
            for c in cells:
                row = t.add_row().cells
                for i, v in enumerate(c):
                    row[i].text = v.replace("**", "")
        table.clear()

    for line in (md or "").replace("\r", "").split("\n"):
        st = line.strip()
        if st.startswith("|"):
            table.append(st)
            continue
        if table:
            flush_table()
        if not st:
            continue
        for v in VIDEO.findall(st):
            key = v.split("?")[0]
            if key not in videos:
                videos[key] = v
            d.add_paragraph().add_run(f"[Video: {len(videos):02d} {key.split('/playback/')[-1].split('/')[0]}.mp4]").italic = True
        st = re.sub(r"\[video[^\]]*\](\(\s*\))?", "", VIDEO.sub("", st), flags=re.I).strip()
        imgs = IMG.findall(st)
        st = IMG.sub("", st).strip()
        if st.startswith("#"):
            level = min(len(st) - len(st.lstrip("#")), 4)
            d.add_heading(st.lstrip("#").strip(), level + 1)
        elif re.match(r"^[-*+]\s+", st):
            _runs(d.add_paragraph(style="List Bullet"), re.sub(r"^[-*+]\s+", "", st))
        elif re.match(r"^\d+[.)]\s+", st):
            _runs(d.add_paragraph(style="List Number"), re.sub(r"^\d+[.)]\s+", "", st))
        elif st.startswith(">"):
            p = d.add_paragraph()
            _runs(p, st.lstrip("> "))
            p.runs and setattr(p.runs[0], "italic", True)
        elif st:
            _runs(d.add_paragraph(), st)
        for alt, src in imgs:
            data = _image(s, src)
            if data:
                try:
                    d.add_picture(io.BytesIO(data), width=Inches(5.8))
                    if alt:
                        d.add_paragraph(alt).runs[0].italic = True
                except Exception:
                    pass
    if table:
        flush_table()


def tag_values(m):
    """Tag values as text; some modules store a tag value as an object."""
    out = []
    for t in m.get("tags") or []:
        v = t.get("value") if isinstance(t, dict) else t
        if isinstance(v, dict):
            v = v.get("label") or v.get("name") or v.get("value")
        if v:
            out.append(str(v))
    return out


def module_doc(s, m, journey):
    d = Document()
    d.styles["Normal"].font.size = Pt(10.5)
    d.core_properties.title = m["title"]
    d.core_properties.comments = f"Avala Learning module {m.get('slug')} (exported for the account holder)"
    d.add_heading(m["title"], 0)
    meta = [("Journey", journey or "-"), ("Type", m.get("type")),
            ("Industry", ", ".join(tag_values(m))),
            ("Estimated time", f"{m.get('estimated_time_minutes') or '?'} min"),
            ("Required", "Yes" if m.get("is_required") else "No"),
            ("Your progress", f"{m.get('progressPercentage', 0)}%")]
    t = d.add_table(rows=0, cols=2)
    t.style = "Light Grid Accent 1"
    for k, v in meta:
        row = t.add_row().cells
        row[0].text, row[1].text = k, str(v or "")
    if m.get("description"):
        d.add_paragraph(m["description"]).runs[0].italic = True
    videos = {}
    quizzes = 0
    for li, lesson in enumerate(sorted(m.get("lessons", []), key=lambda x: x.get("sort_order") or 0), 1):
        d.add_heading(f"Lesson {li}: {lesson.get('title')}", 1)
        if lesson.get("description"):
            d.add_paragraph(lesson["description"]).runs[0].italic = True
        for si, st in enumerate(sorted(lesson.get("steps", []), key=lambda x: x.get("sort_order") or 0), 1):
            if not st.get("is_enabled", True):
                continue
            if st.get("choices"):
                quizzes += 1
                d.add_heading(f"Question {quizzes}", 3)
                markdown(d, s, st.get("markdown"), videos)
                prog = st.get("progress") or {}
                ans = prog.get("quiz_answer")
                picked = set(ans if isinstance(ans, list) else [ans]) if ans else set()
                for c in st["choices"]:
                    mark = ""
                    if c.get("id") in picked or c.get("text") in picked:
                        mark = "  <- your answer" + (" (correct)" if prog.get("is_correct") else
                                                     " (incorrect)" if prog.get("is_correct") is False else "")
                    d.add_paragraph(f"{c.get('text')}{mark}", style="List Bullet")
                for k, label in (("correct_answer_text", "Explanation"), ("incorrect_answer_text", "If wrong")):
                    if st.get(k):
                        d.add_paragraph(f"{label}: {st[k]}").runs[0].italic = True
            elif st.get("practice_config"):
                d.add_heading(f"Practice: {st.get('task_name') or 'task'}", 3)
                markdown(d, s, st.get("markdown"), videos)
                for item in (st["practice_config"] or {}).get("items", [])[:12]:
                    img = (item.get("image") or {}).get("url")
                    data = _image(s, img) if img else None
                    if data:
                        try:
                            d.add_picture(io.BytesIO(data), width=Inches(5.8))
                        except Exception:
                            pass
                    for k in ("question", "instruction", "prompt", "label", "answer"):
                        if item.get(k):
                            d.add_paragraph(f"{k.title()}: {item[k]}")
            else:
                markdown(d, s, st.get("markdown"), videos)
    return d, videos, quizzes


def export(sink, st, cookie, max_modules=400):
    """Returns the number of modules written. Stops cleanly when the session has expired."""
    s = session(cookie)
    me = _get(s, BASE + "/api/auth/me")
    if not me or me.status_code != 200:
        print("avala learning: session expired or invalid - send a new login code to refresh AVALA_LEARN_COOKIE")
        return -1
    lst = _get(s, BASE + "/api/modules")
    if not lst or lst.status_code != 200:
        return 0
    mods = lst.json().get("modules", [])
    jr = _get(s, BASE + "/api/journeys")
    in_journey = {}
    for j in (jr.json().get("journeys", []) if jr and jr.status_code == 200 else []):
        jd = _get(s, f"{BASE}/api/journeys/{j['slug']}")
        for k, jm in enumerate((jd.json().get("modules", []) if jd and jd.status_code == 200 else []), 1):
            mm = jm.get("module") or {}
            in_journey.setdefault(mm.get("id"), (j["title"], jm.get("sort_order") or k))
    done = st.setdefault("learning_done", {})
    n = library(s, sink, st)
    for m in mods:
        if n >= max_modules or sink.full():
            break
        r = _get(s, f"{BASE}/api/modules/{m['slug']}")
        if not r or r.status_code != 200:
            continue
        full = r.json()
        stamp = full.get("content_hash") or full.get("updated_at")
        if done.get(m["id"]) == stamp:
            continue
        journey, order = in_journey.get(m["id"], (None, None))
        if journey:
            folder = f"{ROOT}/Journeys/{safe(journey, 60)}/{int(order):02d} {safe(m['title'], 80)}"
        else:
            topic = next(iter(tag_values(m)), None) or m.get("type") or "Other"
            folder = f"{ROOT}/Modules by topic/{safe(topic, 50)}/{safe(m['title'], 80)}"
        full.update({k: m.get(k) for k in ("progressPercentage",) if k in m})
        try:
            doc, videos, _ = module_doc(s, full, journey)
        except Exception as e:  # one malformed module must not stop the export
            print(f"module skipped ({type(e).__name__})")
            continue
        p = sink.path(f"{folder}/{safe(m['title'], 80)}.docx")
        doc.save(p)
        sink.wrote(p)
        for i, (key, url) in enumerate(videos.items(), 1):
            vid = key.split("/playback/")[-1].split("/")[0]
            sink.download(requests, url, f"{folder}/Videos/{i:02d} {vid}.mp4", 3 * 2 ** 30)
        done[m["id"]] = stamp
        n += 1
        time.sleep(0.3)
    return n


def library(s, sink, st):
    """The Library page: reference videos listed in its page script. Written as one indexed Word file; a video is
    also saved when Vimeo serves a downloadable file for it (most are locked to Avala's own player)."""
    page = _get(s, BASE + "/library")
    if not page or page.status_code != 200:
        return 0
    items = []
    for chunk in set(re.findall(r"/_next/static/chunks/app/library/page-[^\"'\s]+\.js", page.text)):
        js = _get(s, BASE + chunk)
        for m in re.finditer(r"JSON\.parse\('(\[.*?\])'\)", js.text if js else "", re.S):
            try:
                items += [x for x in json.loads(ast.literal_eval("'" + m.group(1) + "'")) if isinstance(x, dict) and x.get("url")]
            except Exception:
                pass
    if not items:
        return 0
    stamp = str(sorted(x.get("id", "") for x in items))
    if st.get("library_stamp") == stamp:
        return 0
    d = Document()
    d.styles["Normal"].font.size = Pt(10.5)
    d.add_heading("Avala reference video library", 0)
    d.add_paragraph(f"{len(items)} reference videos from {BASE}/library. Open the links while signed in to Avala.")
    by_topic = {}
    for x in items:
        topic = next((t for t in x.get("tags", []) if t not in ("reference-video", "vimeo")), "general")
        by_topic.setdefault(topic, []).append(x)
    saved = 0
    for topic in sorted(by_topic):
        d.add_heading(topic.replace("-", " ").title(), 1)
        for x in by_topic[topic]:
            d.add_heading(x.get("title") or x.get("id"), 2)
            if x.get("description"):
                d.add_paragraph(x["description"])
            d.add_paragraph(f"Tags: {', '.join(x.get('tags', []))}")
            d.add_paragraph(f"Video: {x['url']}")
            for k in ("moduleTitle", "lessonTitle"):
                if x.get(k):
                    d.add_paragraph(f"{k.replace('Title', '').title()}: {x[k]}")
            vid = x.get("vimeoId")
            cfg = _get(requests.Session(), f"https://player.vimeo.com/video/{vid}/config",
                       headers={"Referer": BASE + "/", "User-Agent": "Mozilla/5.0"}) if vid else None
            try:
                prog = cfg.json()["request"]["files"]["progressive"] if cfg and cfg.status_code == 200 else []
            except Exception:
                prog = []
            if prog:
                best = max(prog, key=lambda f: f.get("width") or 0)
                if sink.download(requests, best["url"], f"{ROOT}/Library/Videos/{safe(x.get('title') or vid, 90)}.mp4",
                                 3 * 2 ** 30):
                    saved += 1
    p = sink.path(f"{ROOT}/Library/Avala reference video library.docx")
    d.save(p)
    sink.wrote(p)
    st["library_stamp"] = stamp
    print(f"library: {len(items)} reference videos indexed, {saved} downloadable")
    return 1
