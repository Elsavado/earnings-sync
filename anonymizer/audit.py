"""Checks uploaded files for real company identifiers that survived anonymisation.

Usage: python audit.py manifest.json
manifest: {"companies": {code: {"aliases": [...], "ticker": "...", "domains": [...]}},
           "files": [{"path", "ext", "code", "docType", "source"}]}
Prints one JSON summary: totals per document type, the leaked terms (not which file or
company they came from), and how many PDFs have no extractable text.
"""
import collections
import html
import json
import re
import sys
import zipfile


def text_of(path, ext):
    if ext == "pdf":
        import pymupdf as fitz

        with fitz.open(path) as doc:
            return "\n".join(page.get_text() for page in doc), doc.page_count
    if ext in ("docx", "xlsx", "xlsm", "pptx"):
        z = zipfile.ZipFile(path)
        parts = [n for n in z.namelist() if n.endswith(".xml") and "theme" not in n and not n.endswith("app.xml")]
        return "\n".join(html.unescape(" ".join(re.findall(r">([^<]+)<", z.read(n).decode("utf-8", "replace")))) for n in parts), 0
    return "", 0


def main():
    manifest = json.load(open(sys.argv[1], encoding="utf-8"))
    companies = manifest["companies"]
    by_type = collections.defaultdict(lambda: {"files": 0, "with_leaks": 0, "no_text_pdfs": 0})
    leaked_terms = collections.Counter()
    placeholders = collections.Counter()
    errors = 0
    for f in manifest["files"]:
        c = companies.get(f["code"])
        if not c:
            continue
        stats = by_type[f"{f['source']}:{f['docType']}"]
        stats["files"] += 1
        try:
            text, pages = text_of(f["path"], f["ext"])
        except Exception:  # noqa: BLE001
            errors += 1
            continue
        if f["ext"] == "pdf" and pages and len(text.strip()) < 40 * pages:
            stats["no_text_pdfs"] += 1
        terms = [a for a in c["aliases"] if len(a) >= 4]
        if len(c["ticker"]) >= 3:
            terms.append(c["ticker"])
        terms += c.get("domains") or []
        hits = 0
        for t in set(terms):
            n = len(re.findall(rf"(?<![A-Za-z0-9]){re.escape(t)}(?![a-z])", text))
            if n:
                hits += n
                leaked_terms[t] += n
        for tag in ("[PERSON]", "[PHONE]", "[EMAIL]", "[DOMAIN]", "[CIK]", "[REDACTED]"):
            placeholders[tag] += text.count(tag)
        if hits:
            stats["with_leaks"] += 1
    print(json.dumps({
        "checked": sum(s["files"] for s in by_type.values()),
        "unreadable": errors,
        "by_type": dict(sorted(by_type.items())),
        "leaked_terms": leaked_terms.most_common(40),
        "old_placeholders": {k: v for k, v in placeholders.items() if v},
    }))


if __name__ == "__main__":
    main()
