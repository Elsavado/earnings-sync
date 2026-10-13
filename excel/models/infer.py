"""Turns hard-coded figures that are really calculations into formulas.

A typed-in number becomes a formula only when the numbers around it reproduce it exactly
(to rounding), so the workbook shows the same values afterwards:
- column totals:   the contiguous block of numbers directly above sums to it -> =SUM(...)
- row totals:      in a 'Total' column, the numbers to its left sum to it -> =SUM(...)
- subtotals:       rows labelled like profit/EBITDA/net lines equal the difference or sum
                   of two lines above them in the same column -> =B5-B6 / =B5+B6
- growth rates:    rows labelled growth/YoY equal current/prior - 1 of the line above
- margins/ratios:  rows labelled margin/% of equal a line above divided by the revenue line
"""
import re

from .xlsxml import col_letters, escape

SUBTOTAL = re.compile(r'gross (profit|margin)|ebitda|\bebit\b|operating (income|profit)|net (income|profit|debt|cash|revenue|sales|change)|'
                      r'pre-?tax|profit before|income before|earnings before|free cash flow|\bfcf\b|nopat|enterprise value|equity value|'
                      r'cash flow from|net cash|closing|ending balance|end of (year|period)|subtotal|contribution', re.I)
TOTAL = re.compile(r'\btotal\b|\bsum\b|\bsubtotal\b', re.I)
GROWTH = re.compile(r'growth|\byoy\b|y/y|% ?chg|% ?change|increase %', re.I)
MARGIN = re.compile(r'margin|% of (revenue|sales|net sales)|as a % of|% revenue|% sales', re.I)
REVENUE = re.compile(r'^\s*(total )?(net )?(operating )?(revenue|revenues|sales|turnover)\s*(\(.*\))?\s*:?\s*$', re.I)


def _num(cell):
    kind, val, formula = cell
    if kind in ('n', None) and val not in (None, ''):
        try:
            return float(val)
        except ValueError:
            return None
    return None


def _close(a, b):
    return abs(a - b) <= max(abs(b) * 0.0005, 0.011)


def infer(pkg):
    """Edits the package in place. Returns (formulas added, formula cells, numeric constant cells)."""
    added = 0
    total_formulas = 0
    total_constants = 0
    for _, part in pkg.sheets:
        g = pkg.grid(part)
        if not g or len(g) > 400_000:
            continue
        labels = {}
        for (r, c), cell in g.items():
            if c <= 4 and cell[0] in ('s', 'str') and cell[1]:
                labels.setdefault(r, str(cell[1]))
        headers = {}
        for (r, c), cell in g.items():
            if cell[0] in ('s', 'str') and cell[1] and TOTAL.search(str(cell[1])):
                headers.setdefault(c, r)
        revenue_rows = sorted(r for r, t in labels.items() if REVENUE.search(t))
        new = {}
        for (r, c), cell in sorted(g.items()):
            if cell[2] is not None:
                total_formulas += 1
                continue
            v = _num(cell)
            if v is None:
                continue
            total_constants += 1
            if v == 0:
                continue
            label = labels.get(r, '')
            f = None
            # Column total over the block directly above.
            block = []
            rr = r - 1
            while (rr, c) in g and _num(g[(rr, c)]) is not None:
                block.append(_num(g[(rr, c)]))
                rr -= 1
            if len(block) >= 2 and (TOTAL.search(label) or SUBTOTAL.search(label) or len(block) >= 3):
                for k in range(len(block), 1, -1):
                    if _close(sum(block[:k]), v):
                        f = f'SUM({col_letters(c)}{r - k}:{col_letters(c)}{r - 1})'
                        break
            # Row total in a 'Total' column.
            if f is None and c in headers and headers[c] < r:
                row = []
                cc = c - 1
                while (r, cc) in g and _num(g[(r, cc)]) is not None:
                    row.append(_num(g[(r, cc)]))
                    cc -= 1
                if len(row) >= 2 and _close(sum(row), v):
                    f = f'SUM({col_letters(c - len(row))}{r}:{col_letters(c - 1)}{r})'
            above = [(rr, _num(g[(rr, c)])) for rr in range(r - 1, max(0, r - 8), -1)
                     if (rr, c) in g and _num(g[(rr, c)]) is not None]
            # Subtotals: difference or sum of two lines above.
            if f is None and SUBTOTAL.search(label) and len(above) >= 2:
                for i, (ra, a) in enumerate(above):
                    for rb, b in above[i + 1:]:
                        if _close(b - a, v):
                            f = f'{col_letters(c)}{rb}-{col_letters(c)}{ra}'
                        elif _close(a + b, v):
                            f = f'{col_letters(c)}{rb}+{col_letters(c)}{ra}'
                        if f:
                            break
                    if f:
                        break
            # Growth rate of the nearest line above versus the previous column.
            if f is None and GROWTH.search(label) and above:
                ra, cur = above[0]
                prev = _num(g.get((ra, c - 1), (None, None, None)))
                if prev and _close(cur / prev - 1, v):
                    f = f'{col_letters(c)}{ra}/{col_letters(c - 1)}{ra}-1'
            # Margin: a line above divided by the revenue line.
            if f is None and MARGIN.search(label) and above and revenue_rows:
                rev_row = max((x for x in revenue_rows if x < r), default=None)
                rev = _num(g.get((rev_row, c), (None, None, None))) if rev_row else None
                if rev:
                    for ra, a in above:
                        if ra != rev_row and _close(a / rev, v):
                            f = f'{col_letters(c)}{ra}/{col_letters(c)}{rev_row}'
                            break
            if f:
                new[f'{col_letters(c)}{r}'] = f
        if new:
            def cell(ref, attrs, inner):
                f = new.get(ref)
                if not f or '<f' in inner:
                    return None
                attrs2 = re.sub(r'\s+t="n"', '', attrs)
                return f'<c{attrs2}><f>{escape(f)}</f>{inner}</c>'
            pkg.edit_cells(part, cell)
            added += len(new)
    return added, total_formulas + added, total_constants - added
