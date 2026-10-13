"""Removes external links and screens for broken references.

- Formulas that point into other workbooks ([1]Sheet!A1, '[book.xlsx]Sheet'!A1) are replaced
  by their last calculated value, as Excel's 'Break Links' does; the externalLink parts,
  their relationships and content types go.
- Web/file hyperlinks are removed (links to places inside the workbook stay).
- Chart links to external data are removed.
- Workbooks with data connections or Power Query are rejected (removing those cleanly
  would leave tables that point at nothing).
- Any '#REF!' in a formula, or in a defined name that formulas use, rejects the workbook.
"""
import re

from .xlsxml import unescape

EXT_REF = re.compile(r"\[\d+\]|'[^']*\[[^\]]+\.(?:xls[xmb]?|csv)\][^']*'!|\[[^\]]+\.(?:xls[xmb]?|csv)\]", re.I)


class Reject(Exception):
    pass


def _remove_rel(pkg, rels_part, predicate):
    if rels_part not in pkg.parts:
        return []
    text = pkg.text(rels_part)
    removed = []

    def repl(m):
        el = m.group(0)
        if predicate(el):
            rid = re.search(r'\bId="([^"]+)"', el)
            removed.append((rid.group(1) if rid else None, re.search(r'\bTarget="([^"]*)"', el).group(1)))
            return ''
        return el

    new = re.sub(r'<Relationship\b[^>]*/>', repl, text)
    if new != text:
        pkg.put(rels_part, new)
    return removed


def _drop_content_type(pkg, part):
    ct = pkg.text('[Content_Types].xml')
    new = re.sub(rf'<Override[^>]*PartName="/{re.escape(part)}"[^>]*/>', '', ct)
    if new != ct:
        pkg.put('[Content_Types].xml', new)


def clean(pkg):
    """Returns stats; raises Reject for workbooks that cannot be cleaned safely."""
    stats = {'external_formulas': 0, 'hyperlinks': 0, 'link_parts': 0}
    if any(p == 'xl/connections.xml' or p.startswith('xl/queryTables/') or p.startswith('customXml/item') and
           b'DataMashup' in pkg.parts.get(p, b'') for p in pkg.parts):
        raise Reject('data connections / Power Query')

    # Defined names: external ones are deleted, #REF! ones rejected if any formula uses them.
    wb = pkg.text('xl/workbook.xml')
    all_formulas = ' '.join(unescape(f) for p in [p for _, p in pkg.sheets]
                            for f in re.findall(r'<f(?:\s[^>]*)?>(.*?)</f>', pkg.text(p), re.S))
    if '#REF!' in all_formulas:
        raise Reject('#REF! in formulas')

    def name_repl(m):
        body = unescape(m.group(2))
        name = re.search(r'\bname="([^"]+)"', m.group(1)).group(1)
        if EXT_REF.search(body) or '#REF!' in body:
            if '#REF!' in body and not name.startswith('_xlnm.') and re.search(rf'(?<![\w.]){re.escape(name)}(?![\w(])', all_formulas):
                raise Reject(f'defined name {name} is #REF! and in use')
            return ''
        return m.group(0)

    wb = re.sub(r'(<definedName\b[^>]*>)(.*?)</definedName>', name_repl, wb, flags=re.S)
    wb = re.sub(r'<externalReferences>.*?</externalReferences>', '', wb, flags=re.S)
    wb = re.sub(r'<definedNames>\s*</definedNames>', '', wb)
    # Make Excel recalculate everything (inferred formulas, broken links) when opened.
    if '<calcPr' in wb:
        wb = re.sub(r'<calcPr\b([^>]*?)(/?)>', lambda m: '<calcPr' + re.sub(r'\s*fullCalcOnLoad="[^"]*"', '', m.group(1)) +
                    ' fullCalcOnLoad="1"' + m.group(2) + '>', wb, count=1)
    pkg.put('xl/workbook.xml', wb)

    for rid, target in _remove_rel(pkg, 'xl/_rels/workbook.xml.rels', lambda el: 'externalLink' in el or 'calcChain' in el):
        part = 'xl/' + target.lstrip('/').replace('xl/', '', 1) if not target.startswith('/') else target.lstrip('/')
        part = part.replace('xl/xl/', 'xl/')
        rels = part.rsplit('/', 1)
        pkg.drop(part)
        pkg.drop(f'{rels[0]}/_rels/{rels[1]}.rels')
        _drop_content_type(pkg, part)
        stats['link_parts'] += 'externalLink' in part
    for p in [p for p in pkg.parts if p.startswith('xl/externalLinks/') or p == 'xl/calcChain.xml']:
        pkg.drop(p)
        _drop_content_type(pkg, p)

    for _, part in pkg.sheets:
        # Shared-formula groups whose master points outside the workbook lose every member.
        text = pkg.text(part)
        bad_si = set()
        for m in re.finditer(r'<f\b([^>]*)>(.*?)</f>', text, re.S):
            if EXT_REF.search(unescape(m.group(2))):
                si = re.search(r'\bsi="(\d+)"', m.group(1))
                if si and 't="shared"' in m.group(1):
                    bad_si.add(si.group(1))

        def cell(ref, attrs, inner):
            f = re.search(r'<f\b([^>]*?)(?:/>|>(.*?)</f>)', inner, re.S)
            if not f:
                return None
            ext = EXT_REF.search(unescape(f.group(2) or ''))
            si = re.search(r'\bsi="(\d+)"', f.group(1))
            if ext or (si and si.group(1) in bad_si and 't="shared"' in f.group(1)):
                stats['external_formulas'] += 1
                return f'<c{attrs}>{inner[:f.start()] + inner[f.end():]}</c>'
            return None

        pkg.edit_cells(part, cell)
        # Hyperlinks to outside the workbook.
        rp, rels = pkg.rels(part)
        external = {rid for rid, (typ, _, mode) in rels.items() if typ.endswith('/hyperlink') and mode == 'External'}
        if external:
            text = pkg.text(part)
            new = re.sub(r'<hyperlink\b[^>]*/>', lambda m: '' if any(f'"{rid}"' in m.group(0) for rid in external) else m.group(0), text)
            new = re.sub(r'<hyperlinks>\s*</hyperlinks>', '', new)
            stats['hyperlinks'] += len(external)
            pkg.put(part, new)
            _remove_rel(pkg, rp, lambda el: 'TargetMode="External"' in el and '/hyperlink' in el)
    # Hyperlinks in drawings/shapes and external chart data.
    for part in [p for p in pkg.parts if re.match(r'xl/(drawings|charts)/_rels/.*\.rels$', p)]:
        removed = _remove_rel(pkg, part, lambda el: 'TargetMode="External"' in el)
        if removed:
            owner = part.replace('_rels/', '').removesuffix('.rels')
            text = pkg.text(owner)
            for rid, _ in removed:
                text = re.sub(rf'<a:hlinkClick\b[^>]*r:id="{rid}"[^>]*/>', '', text)
                text = re.sub(rf'<c:externalData\b[^>]*r:id="{rid}"[^>]*>.*?</c:externalData>', '', text, flags=re.S)
                text = re.sub(rf'<c:externalData\b[^>]*r:id="{rid}"[^>]*/>', '', text)
            pkg.put(owner, text)
            stats['hyperlinks'] += len(removed)
    return stats


def has_external(pkg):
    """True if anything still points outside the workbook (used as a final gate)."""
    if any(p.startswith('xl/externalLinks/') for p in pkg.parts):
        return True
    for p, data in pkg.parts.items():
        if p.endswith('.rels') and b'TargetMode="External"' in data:
            return True
    for _, part in pkg.sheets:
        for f in re.findall(r'<f(?:\s[^>]*)?>(.*?)</f>', pkg.text(part), re.S):
            if EXT_REF.search(unescape(f)):
                return True
    return False
