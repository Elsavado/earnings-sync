"""Strips pictures from a workbook package: company logos and any other embedded image.

Removed: pictures placed on sheets (drawing anchors holding <xdr:pic>, including inside
groups), picture fills in shapes and charts, header/footer images, and sheet background
images, together with their relationships and the image files themselves. Data-driven charts
are not pictures and stay.
"""
import posixpath
import re

# Any namespace prefix, or none: <xdr:twoCellAnchor>, <twoCellAnchor>, ...
ANCHOR = re.compile(r'<((?:\w+:)?)(twoCellAnchor|oneCellAnchor|absoluteAnchor)\b.*?</\1\2>', re.S)
PIC = re.compile(r'<(?:\w+:)?pic[\s>/]')


def _drop_rels(pkg, rels_part, rids):
    if rels_part not in pkg.parts or not rids:
        return
    text = pkg.text(rels_part)
    for rid in rids:
        text = re.sub(rf'<Relationship\b[^>]*\bId="{re.escape(rid)}"[^>]*/>', '', text)
    pkg.put(rels_part, text)


def _rels_path(part):
    d, b = posixpath.split(part)
    return posixpath.join(d, '_rels', b + '.rels')


def strip(pkg):
    """Removes all pictures in place. Returns how many were removed."""
    removed = 0
    # Pictures on sheets (and picture fills of shapes) live in drawing parts.
    for part in [p for p in pkg.parts if re.match(r'xl/drawings/drawing\d+\.xml$', p)]:
        text = pkg.text(part)
        kept = []
        for m in ANCHOR.finditer(text):
            if PIC.search(m.group(0)):
                removed += 1
                kept.append((m.start(), m.end()))
        for a, b in reversed(kept):
            text = text[:a] + text[b:]
        n = len(re.findall(r'<a:blipFill\b', text))
        text = re.sub(r'<a:blipFill\b.*?</a:blipFill>', '<a:noFill/>', text, flags=re.S)
        removed += n
        pkg.put(part, text)
    # Picture fills inside charts.
    for part in [p for p in pkg.parts if re.match(r'xl/charts/chart\d+\.xml$', p)]:
        text = pkg.text(part)
        n = len(re.findall(r'<a:blipFill\b', text))
        if n:
            pkg.put(part, re.sub(r'<a:blipFill\b.*?</a:blipFill>', '<a:noFill/>', text, flags=re.S))
            removed += n
    # Sheet backgrounds and header/footer images.
    for part in [p for p in pkg.parts if re.match(r'xl/(worksheets|chartsheets)/\w+\.xml$', p)]:
        text = pkg.text(part)
        rids = re.findall(r'<picture\b[^>]*r:id="([^"]+)"[^>]*/>', text) + re.findall(r'<legacyDrawingHF\b[^>]*r:id="([^"]+)"[^>]*/>', text)
        if not rids:
            continue
        text = re.sub(r'<picture\b[^>]*/>', '', text)
        text = re.sub(r'<legacyDrawingHF\b[^>]*/>', '', text)
        # '&G' in a header/footer is the placeholder for its picture.
        text = re.sub(r'(<(?:odd|even|first)(?:Header|Footer)>[^<]*?)&amp;G', r'\1', text)
        pkg.put(part, text)
        _drop_rels(pkg, _rels_path(part), rids)
        removed += len(rids)
    # Image relationships nothing points at any more, then the image files themselves.
    for rels_part in [p for p in pkg.parts if p.endswith('.rels') and ('drawings/_rels' in p or 'charts/_rels' in p)]:
        owner = rels_part.replace('_rels/', '').removesuffix('.rels')
        if owner not in pkg.parts:
            continue
        body = pkg.text(owner)
        text = pkg.text(rels_part)
        stale = [rid for rid, typ in re.findall(r'<Relationship\b[^>]*\bId="([^"]+)"[^>]*\bType="([^"]+)"', text)
                 if typ.endswith('/image') and f'"{rid}"' not in body]
        stale += [rid for typ, rid in re.findall(r'<Relationship\b[^>]*\bType="([^"]+)"[^>]*\bId="([^"]+)"', text)
                  if typ.endswith('/image') and f'"{rid}"' not in body]
        _drop_rels(pkg, rels_part, set(stale))
    referenced = set()
    for p in pkg.parts:
        if p.endswith('.rels'):
            base = posixpath.dirname(posixpath.dirname(p))
            for t in re.findall(r'Target="([^"]+)"', pkg.text(p)):
                referenced.add(posixpath.normpath(posixpath.join(base, t)) if not t.startswith('/') else t.lstrip('/'))
    for p in [p for p in pkg.parts if p.startswith('xl/media/')]:
        if p not in referenced:
            pkg.drop(p)
    # VML parts used only for header/footer pictures.
    for p in [p for p in pkg.parts if re.match(r'xl/drawings/vmlDrawing\d+\.vml$', p) and p not in referenced]:
        pkg.drop(p)
        pkg.drop(_rels_path(p))
    return removed
