"""Reads and edits .xlsx/.xlsm packages at the XML level.

Parts are parsed for reading only; every change is a targeted text edit on the raw XML, so
namespace prefixes, charts, shapes, pivot caches, VBA and formatting are left byte-for-byte
as they were (re-serialising with a generic XML library would rename prefixes and make
Excel report the file as damaged).
"""
import html
import posixpath
import re
import zipfile
from xml.etree import ElementTree as ET

NS_M = 'http://schemas.openxmlformats.org/spreadsheetml/2006/main'
NS_R = 'http://schemas.openxmlformats.org/officeDocument/2006/relationships'
NS_REL = 'http://schemas.openxmlformats.org/package/2006/relationships'
M, R, REL = '{%s}' % NS_M, '{%s}' % NS_R, '{%s}' % NS_REL
CELL_RE = re.compile(r'^\$?([A-Z]{1,3})\$?(\d+)$')
# One <c> element: attributes, then either self-closing or content.
C_ELEMENT = re.compile(r'<c\b([^>]*?)(/>|>(.*?)</c>)', re.S)
ATTR_R = re.compile(r'\br="([A-Z]{1,3}\d+)"')


def col_index(letters):
    n = 0
    for ch in letters:
        n = n * 26 + ord(ch) - 64
    return n


def col_letters(n):
    s = ''
    while n:
        n, r = divmod(n - 1, 26)
        s = chr(65 + r) + s
    return s


def unescape(s):
    return html.unescape(s)


def escape(s):
    return s.replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')


class Package:
    def __init__(self, path):
        with zipfile.ZipFile(path) as z:
            self.parts = {i.filename: z.read(i.filename) for i in z.infolist() if not i.is_dir()}
        self.order = list(self.parts)
        self.strings = self._shared_strings()
        self.sheets = self._sheets()  # [(name, part path)]

    def text(self, part):
        return self.parts[part].decode('utf-8', errors='replace')

    def put(self, part, text):
        self.parts[part] = text.encode('utf-8')

    def drop(self, part):
        self.parts.pop(part, None)

    def rels(self, part):
        d, b = posixpath.split(part)
        rp = posixpath.join(d, '_rels', b + '.rels')
        if rp not in self.parts:
            return rp, {}
        out = {}
        for r in ET.fromstring(self.parts[rp]).findall(f'{REL}Relationship'):
            out[r.get('Id')] = (r.get('Type', ''), r.get('Target', ''), r.get('TargetMode', ''))
        return rp, out

    def _shared_strings(self):
        if 'xl/sharedStrings.xml' not in self.parts:
            return []
        root = ET.fromstring(self.parts['xl/sharedStrings.xml'])
        return [''.join(t.text or '' for t in si.iter(f'{M}t')) for si in root.findall(f'{M}si')]

    def _sheets(self):
        wb = ET.fromstring(self.parts['xl/workbook.xml'])
        _, rels = self.rels('xl/workbook.xml')
        out = []
        for s in wb.iter(f'{M}sheet'):
            rid = s.get(f'{R}id')
            if rid in rels:
                target = rels[rid][1]
                path = target.lstrip('/') if target.startswith('/') else posixpath.normpath(posixpath.join('xl', target))
                if path in self.parts and 'worksheet' in rels[rid][0]:
                    out.append((s.get('name'), path))
        return out

    def grid(self, sheet_part):
        """{(row, col): (kind, value, formula)}; formula '<shared>' marks a shared-formula child."""
        out = {}
        root = ET.fromstring(self.parts[sheet_part])
        for c in root.iter(f'{M}c'):
            m = CELL_RE.match(c.get('r') or '')
            if not m:
                continue
            f, v = c.find(f'{M}f'), c.find(f'{M}v')
            kind = c.get('t', 'n')
            val = v.text if v is not None else None
            if kind == 's' and val is not None:
                try:
                    val = self.strings[int(val)]
                except (ValueError, IndexError):
                    val = None
            elif kind == 'inlineStr':
                is_ = c.find(f'{M}is')
                val = ''.join(x.text or '' for x in is_.iter(f'{M}t')) if is_ is not None else None
                kind = 'str'
            formula = None
            if f is not None:
                formula = f.text if (f.text or '').strip() else ('<shared>' if f.get('t') == 'shared' else '')
            out[(int(m.group(2)), col_index(m.group(1)))] = (kind, val, formula)
        return out

    def texts(self, limit=6000):
        """Short text values from shared strings and every sheet's inline strings."""
        out = [t for t in self.strings if t and len(t) < 300]
        for _, part in self.sheets:
            if len(out) >= limit:
                break
            for m in re.finditer(r'<is>(.*?)</is>', self.text(part), re.S):
                t = unescape(''.join(re.findall(r'<t(?:\s[^>]*)?>(.*?)</t>', m.group(1), re.S)))
                if t and len(t) < 300:
                    out.append(t)
        return out[:limit]

    def edit_cells(self, sheet_part, fn):
        """Calls fn(ref, attrs, inner) for every <c>; a returned string replaces the element."""
        text = self.text(sheet_part)
        changed = [False]

        def repl(m):
            attrs, inner = m.group(1), m.group(3) or ''
            ref = ATTR_R.search(attrs)
            if not ref:
                return m.group(0)
            out = fn(ref.group(1), attrs, inner)
            if out is None:
                return m.group(0)
            changed[0] = True
            return out

        new = C_ELEMENT.sub(repl, text)
        if changed[0]:
            self.put(sheet_part, new)
        return changed[0]

    def save(self, path):
        with zipfile.ZipFile(path, 'w', zipfile.ZIP_DEFLATED) as z:
            for name in self.order:
                if name in self.parts:
                    z.writestr(name, self.parts[name])
            for name in self.parts:
                if name not in self.order:
                    z.writestr(name, self.parts[name])
