"""Removes empty worksheets and measures how complete the remaining ones are.

A tab with no cell content and no drawing (chart, picture, shape) is deleted, unless a
formula or defined name refers to it. Removal edits the workbook part list, relationships,
content types, defined-name sheet indices and the active-tab setting together, so the file
stays valid.
"""
import re

from .xlsxml import unescape


def _referenced(pkg, name):
    q = "'" + name.replace("'", "''") + "'!"
    plain = re.compile(rf'(?<![\w.\'])\b{re.escape(name)}!') if re.fullmatch(r'[A-Za-z_][\w.]*', name) else None
    texts = [pkg.text('xl/workbook.xml')] + [pkg.text(p) for _, p in pkg.sheets] + \
            [pkg.text(p) for p in pkg.parts if p.startswith('xl/charts/chart')]
    for t in texts:
        t = unescape(t)
        if q in t or (plain and plain.search(t)):
            return True
    return False


def is_empty(pkg, part, max_cells=3):
    """No drawing and at most max_cells filled cells (a blank or title-only placeholder tab)."""
    x = pkg.text(part)
    if re.search(r'<(drawing|legacyDrawing|picture|oleObjects|controls)\b', x):
        return False
    filled = 0
    for kind, val, formula in pkg.grid(part).values():
        if formula:
            return False
        if val not in (None, '') and str(val).strip():
            filled += 1
            if filled > max_cells:
                return False
    return True


def drop_empty(pkg):
    """Deletes empty, unreferenced worksheets. Returns the names removed."""
    removed = []
    for name, part in list(pkg.sheets):
        if len(pkg.sheets) <= 1:
            break
        if not is_empty(pkg, part) or _referenced(pkg, name):
            continue
        wb = pkg.text('xl/workbook.xml')
        tags = re.findall(r'<sheet\b[^>]*/>', wb)
        idx = next((i for i, t in enumerate(tags) if f'name="{name}"' in unescape(t) or f'name="{name}"' in t), None)
        if idx is None:
            continue
        rid = re.search(r'r:id="([^"]+)"', tags[idx]).group(1)
        wb = wb.replace(tags[idx], '', 1)

        def fix_local(m):
            k = int(m.group(2))
            if k == idx:
                return ''
            return m.group(0).replace(f'localSheetId="{k}"', f'localSheetId="{k - 1}"') if k > idx else m.group(0)

        wb = re.sub(r'(<definedName\b[^>]*localSheetId="(\d+)"[^>]*>.*?</definedName>)', fix_local, wb, flags=re.S)
        wb = re.sub(r'\b(activeTab|firstSheet)="\d+"', r'\1="0"', wb)
        pkg.put('xl/workbook.xml', wb)
        rels = pkg.text('xl/_rels/workbook.xml.rels')
        pkg.put('xl/_rels/workbook.xml.rels', re.sub(rf'<Relationship\b[^>]*\bId="{rid}"[^>]*/>', '', rels))
        ct = pkg.text('[Content_Types].xml')
        pkg.put('[Content_Types].xml', re.sub(rf'<Override[^>]*PartName="/{re.escape(part)}"[^>]*/>', '', ct))
        pkg.drop(part)
        d, b = part.rsplit('/', 1)
        pkg.drop(f'{d}/_rels/{b}.rels')
        # Selected-tab flags would otherwise point at nothing; select the first remaining sheet.
        pkg.sheets = [(n, p) for n, p in pkg.sheets if p != part]
        removed.append(name)
    if removed and pkg.sheets:
        first = pkg.sheets[0][1]
        for _, p in pkg.sheets:
            t = re.sub(r'\s*tabSelected="1"', '', pkg.text(p))
            if p == first:
                t = re.sub(r'<sheetView\b', '<sheetView tabSelected="1"', t, count=1)
            pkg.put(p, t)
    return removed


def sparse_sheets(pkg, min_cells=12):
    """Names of non-empty sheets with very little content and no drawing (placeholder tabs)."""
    out = []
    for name, part in pkg.sheets:
        x = pkg.text(part)
        if re.search(r'<(drawing|legacyDrawing|picture)\b', x):
            continue
        filled = sum(1 for k, v, f in pkg.grid(part).values() if f or (v not in (None, '') and str(v).strip()))
        if filled < min_cells:
            out.append(name)
    return out
