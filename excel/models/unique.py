"""Makes every model look and read differently (user, 2026-10-20: "every model should look unique").

A profile is drawn deterministically from the model's key (its secret-keyed code), so the same model always gets the
same look while no two models share one: colour theme, font, sheet names, row labels, number style, gridlines, zoom
and tab colours. apply() rewrites the finished workbook - renamed sheets are carried through every formula, chart
reference, hyperlink and data validation, and enterprise.references_ok() re-checks the result.

Content-level uniqueness (company-specific line items, volatility-sized scenarios, horizons and optional modules) is
built by the model builders from the same profile; see enterprise.py.
"""
import hashlib
import random
import re

from openpyxl.styles import Font, PatternFill

# primary (headings, header fill), secondary (forecast headers), input fill, accent (tabs)
PALETTES = [('1F3864', '2E75B6', 'FFF2CC', '1F3864'), ('0B4F6C', '01BAEF', 'FDF6E3', '0B4F6C'),
            ('5B1A2B', '9E2A2B', 'FFF4E6', '7A1F35'), ('1E4D2B', '3A7D44', 'F1F8E9', '2E6B3A'),
            ('2F3640', 'E1702D', 'FFF7EC', '2F3640'), ('3C1E5A', '7B4FA6', 'F6F0FB', '4E2A73'),
            ('263238', 'B08D2E', 'FFFBEA', '37474F'), ('12355B', '4F81BD', 'EAF1FB', '12355B'),
            ('004D40', '00897B', 'E0F2F1', '00695C'), ('3E2723', '8D6E63', 'FBF3EE', '5D4037'),
            ('1A237E', '3949AB', 'E8EAF6', '283593'), ('33272A', 'C0392B', 'FDEDEC', '922B21')]
FONTS = ['Calibri', 'Arial', 'Segoe UI', 'Verdana', 'Tahoma', 'Cambria', 'Georgia', 'Trebuchet MS']
SHEETS = {
    'Cover': ['Cover', 'Contents', 'Index', 'Read Me', 'Model Map'],
    'Dashboard': ['Dashboard', 'Summary', 'Executive Summary', 'Overview', 'Key Outputs'],
    'Historical Data': ['Historical Data', 'Historicals', 'Actuals', 'Reported Data', 'Source Data'],
    'Scenario Inputs': ['Scenario Inputs', 'Scenarios', 'Scenario Control', 'Cases', 'Scenario Settings'],
    'Assumptions': ['Assumptions', 'Drivers', 'Forecast Drivers', 'Key Assumptions', 'Driver Analysis'],
    'Income Statement': ['Income Statement', 'P&L', 'Profit & Loss', 'IS', 'Statement of Operations'],
    'Balance Sheet': ['Balance Sheet', 'BS', 'Financial Position', 'Statement of Fin Position'],
    'Cash Flow': ['Cash Flow', 'CF', 'Cash Flow Statement', 'Cash Flows'],
    'Ratios': ['Ratios', 'KPIs', 'Ratio Analysis', 'Metrics', 'Key Ratios'],
    'Supporting Schedules': ['Supporting Schedules', 'Schedules', 'Workings', 'Supporting Calcs', 'Sub-schedules'],
    'Market Inputs': ['Market Inputs', 'Market Data', 'Valuation Inputs', 'Capital Markets'],
    'Valuation': ['Valuation', 'Valuation Summary', 'Value Bridge'],
    'Sensitivity': ['Sensitivity', 'Sensitivities', 'Value Sensitivity'],
    'Football Field': ['Football Field', 'Valuation Range', 'Value Ranges'],
    'Transaction Inputs': ['Transaction Inputs', 'Deal Inputs', 'Deal Terms'],
    'Sources & Uses': ['Sources & Uses', 'S&U', 'Funding at Close'],
    'LBO Model': ['LBO Model', 'LBO', 'Buyout Model', 'Debt & Returns'],
    'Returns': ['Returns', 'Sponsor Returns', 'Equity Returns'],
    'Budget Inputs': ['Budget Inputs', 'Budget Settings', 'Planning Inputs B'],
    'Monthly Budget': ['Monthly Budget', 'Budget by Month', 'Monthly Plan'],
    'Department Plan': ['Department Plan', 'Cost Centres', 'Opex by Function'],
    'Variance Analysis': ['Variance Analysis', 'Budget vs Actual', 'BvA'],
    'Credit Inputs': ['Credit Inputs', 'Covenant Inputs', 'Credit Settings'],
    'Credit Analysis': ['Credit Analysis', 'Credit Metrics', 'Credit Profile'],
    'Bank Inputs': ['Bank Inputs', 'Bank Settings', 'Capital & Risk Inputs'],
    'NII Build': ['NII Build', 'Net Interest Income', 'NII'],
    'Credit Quality': ['Credit Quality', 'Asset Quality', 'Loan Book'],
    'Capital': ['Capital', 'Capital Planning', 'Regulatory Capital'],
    'Liquidity & Funding': ['Liquidity & Funding', 'Funding', 'Liquidity'],
    'Returns & Efficiency': ['Returns & Efficiency', 'Profitability', 'Returns'],
    'Projection': ['Projection', 'Population Projection', 'Cohort Projection'],
    'Service Planning': ['Service Planning', 'Service Needs', 'Infrastructure Needs'],
    'Fiscal Accounts': ['Fiscal Accounts', 'Fiscal Table', 'Government Accounts'],
    'Debt Sustainability': ['Debt Sustainability', 'DSA', 'Debt Dynamics'],
    'Macro Framework': ['Macro Framework', 'Macro Table', 'Economic Outlook'],
    'Project Cash Flows': ['Project Cash Flows', 'Project Flows', 'Cash Flow Profile'],
    'Economic Analysis': ['Economic Analysis', 'Appraisal Results', 'CBA Results'],
    'Company Detail': ['Company Detail', 'Reported Line Items', 'Additional Line Items', 'Line-Item Detail'],
    'R&D Analysis': ['R&D Analysis', 'R&D', 'Research & Development'],
    'Share-Based Pay': ['Share-Based Pay', 'SBC Analysis', 'Equity Compensation'],
    'Planning Inputs': ['Planning Inputs', 'Service Standards', 'Planning Standards'],
    'Project Inputs': ['Project Inputs', 'Appraisal Inputs', 'Project Assumptions'],
    'Stress Test': ['Stress Test', 'Severe Stress', 'Capital Stress'],
    'Interest Rate Risk': ['Interest Rate Risk', 'IRRBB', 'Rate Shocks'],
    'Valuation Model': ['Valuation Model', 'DDM & Residual Income', 'Equity Valuation'],
    'DDM Sensitivity': ['DDM Sensitivity', 'Value Sensitivity', 'Ke x g Grid'],
    'IRR Sensitivity': ['IRR Sensitivity', 'Returns Grid', 'IRR Grid'],
    'WACC': ['WACC', 'Cost of Capital', 'Discount Rate'],
    'DCF': ['DCF', 'Free Cash Flow', 'UFCF & Discounting'],
}
LABELS = {
    'Revenue': ['Revenue', 'Net sales', 'Total revenues', 'Net revenues', 'Sales'],
    'Cost of revenue': ['Cost of revenue', 'Cost of sales', 'Cost of goods sold', 'Direct costs'],
    'Gross profit': ['Gross profit', 'Gross income', 'Gross margin (value)'],
    'Operating expenses': ['Operating expenses', 'SG&A and other operating costs', 'Operating costs', 'Overheads'],
    'Operating income (EBIT)': ['Operating income (EBIT)', 'EBIT', 'Operating profit', 'Income from operations'],
    'Net income': ['Net income', 'Net earnings', 'Profit for the year', 'Net profit'],
    'Cash and equivalents': ['Cash and equivalents', 'Cash and cash equivalents', 'Cash & short-term investments', 'Cash'],
    'Accounts receivable': ['Accounts receivable', 'Trade receivables', 'Receivables, net', 'Debtors'],
    'Inventory': ['Inventory', 'Inventories', 'Stock'],
    'Accounts payable': ['Accounts payable', 'Trade payables', 'Payables', 'Creditors'],
    'Capital expenditure': ['Capital expenditure', 'Capex', 'Purchases of PP&E', 'Capital spending'],
    'Long-term debt': ['Long-term debt', 'Long-term borrowings', 'Non-current debt'],
    "Shareholders' equity": ["Shareholders' equity", "Stockholders' equity", "Shareholders' funds", 'Total equity (parent)'],
    'Free cash flow (CFO - capex)': ['Free cash flow (CFO - capex)', 'FCF', 'Free cash flow'],
    'Depreciation & amortisation': ['Depreciation & amortisation', 'D&A', 'Depreciation and amortization'],
    'Income tax expense': ['Income tax expense', 'Tax charge', 'Provision for income taxes'],
    'Interest expense': ['Interest expense', 'Finance costs', 'Interest charges'],
    'Net interest income': ['Net interest income', 'NII', 'Net interest revenue'],
    'Pre-provision net revenue': ['Pre-provision net revenue', 'PPNR', 'Pre-provision profit'],
    'Population': ['Population', 'Residents', 'Total population'],
}
SCENARIO_NAMES = [('Base', 'Upside', 'Downside'), ('Base', 'Bull', 'Bear'), ('Management', 'Optimistic', 'Stress'),
                  ('Central', 'High', 'Low'), ('Plan', 'Stretch', 'Conservative'), ('Base case', 'Upside case', 'Downside case')]
NUMBER_STYLES = ['#,##0.0_);(#,##0.0);"–"_)', '#,##0.0;[Red]-#,##0.0;"-"', '#,##0_);(#,##0);"-"_)',
                 '#,##0.0_);[Red](#,##0.0);"–"_)', '#,##0.00_);(#,##0.00);"–"_)', '#,##0;-#,##0;"–"']
BASE_NUM = '#,##0.0_);(#,##0.0);"–"_)'
BASE = ('1F3864', '2E75B6', 'FFF2CC')


class Profile:
    def __init__(self, key):
        self.seed = int(hashlib.sha256(key.encode()).hexdigest()[:16], 16)
        r = self.rng = random.Random(self.seed)
        self.palette = r.choice(PALETTES)
        self.font = r.choice(FONTS)
        self.sheet_names = {k: r.choice(v) for k, v in SHEETS.items()}
        self.labels = {k: r.choice(v) for k, v in LABELS.items()}
        self.scenarios = r.choice(SCENARIO_NAMES)
        self.number = r.choice(NUMBER_STYLES)
        self.gridlines = r.random() < 0.3
        self.zoom = r.choice([80, 85, 90, 100, 100, 110])
        self.label_width = r.choice([40, 44, 46, 50, 54])
        self.col_width = r.choice([11, 12, 13, 14])
        self.order_seed = r.random()

    def pick(self, options):
        return self.rng.choice(options)


def _rename_in_formula(f, mapping):
    for old, new in mapping.items():
        q_new = "'" + new.replace("'", "''") + "'"
        f = f.replace("'" + old.replace("'", "''") + "'!", q_new + '!')
        if re.fullmatch(r'[A-Za-z_][A-Za-z0-9_.]*', old):
            f = re.sub(rf"(?<![A-Za-z0-9_.'!]){re.escape(old)}!", q_new + '!', f)
    return f


def _color(c):
    return (c or '')[-6:].upper() if isinstance(c, str) else ''


def apply(wb, profile, fixed=('Checks',)):
    """Renames sheets (with every reference), relabels rows and restyles the workbook. Returns {old: new} names."""
    p1, p2, pin, accent = profile.palette
    cmap = {BASE[0]: p1, BASE[1]: p2, BASE[2]: pin}
    taken = set(wb.sheetnames)
    mapping = {}
    for ws in wb.worksheets:
        new = profile.sheet_names.get(ws.title)
        if new and new != ws.title and ws.title not in fixed and new not in taken:
            mapping[ws.title] = new
            taken.add(new)
    for ws in wb.worksheets:
        for row in ws.iter_rows():
            for c in row:
                v = c.value
                if isinstance(v, str):
                    if v.startswith('='):
                        if mapping:
                            c.value = _rename_in_formula(v, mapping)
                    elif v in profile.labels and c.column == 1:
                        c.value = profile.labels[v]
                    elif v in ('Base', 'Upside', 'Downside') and c.font and c.font.b:
                        c.value = profile.scenarios[('Base', 'Upside', 'Downside').index(v)]
                    elif mapping and v in mapping and c.hyperlink is None:
                        c.value = mapping[v]
                if c.hyperlink is not None and c.hyperlink.location:
                    loc = c.hyperlink.location
                    for old, new in mapping.items():
                        if loc.startswith(f"'{old}'!") or loc.startswith(f'{old}!'):
                            c.hyperlink.location = f"'{new}'!A1"
                            c.hyperlink.display = new
                            if c.value == old:
                                c.value = new
                if c.has_style:
                    f = c.font
                    col = _color(f.color.rgb) if f.color is not None and f.color.type == 'rgb' else ''
                    c.font = Font(name=profile.font, size=f.sz, bold=f.b, italic=f.i, underline=f.u,
                                  color=cmap.get(col, f.color))
                    fl = c.fill
                    if fl is not None and fl.fill_type == 'solid':
                        fc = _color(fl.fgColor.rgb) if fl.fgColor is not None and fl.fgColor.type == 'rgb' else ''
                        if fc in cmap:
                            c.fill = PatternFill('solid', fgColor=cmap[fc])
                    if c.number_format == BASE_NUM:
                        c.number_format = profile.number
        for dv in ws.data_validations.dataValidation:
            if dv.formula1 and mapping:
                dv.formula1 = _rename_in_formula(dv.formula1, mapping)
        ws.sheet_view.showGridLines = profile.gridlines
        ws.sheet_view.zoomScale = profile.zoom
        ws.sheet_properties.tabColor = accent if ws.title in ('Cover', 'Dashboard') else None
        if ws.column_dimensions['A'].width and ws.column_dimensions['A'].width >= 40:
            ws.column_dimensions['A'].width = profile.label_width
    for ws in wb.worksheets:  # chart series hold their ranges as text
        for chart in getattr(ws, '_charts', []):
            for s in chart.series:
                for ref in (s.val, s.cat, s.tx):
                    for r in (getattr(ref, 'numRef', None), getattr(ref, 'strRef', None)):
                        if r is not None and r.f and mapping:
                            f = r.f if r.f.startswith('=') else '=' + r.f
                            r.f = _rename_in_formula(f, mapping)[1:]
    for old, new in mapping.items():
        wb[old].title = new
    for dn in list(getattr(wb, 'defined_names', {}).values()) if hasattr(wb.defined_names, 'values') else []:
        if dn.attr_text and mapping:
            dn.attr_text = _rename_in_formula(dn.attr_text, mapping)
    # Supporting sheets move around a little: the cover stays first, the checks last, the statements in order.
    movable = [ws for ws in wb.worksheets if ws.title not in (mapping.get(n, n) for n in
               ('Cover', 'Dashboard', 'Historical Data', 'Income Statement', 'Balance Sheet', 'Cash Flow', 'Checks'))]
    if len(movable) > 2 and profile.order_seed < 0.6:
        r = random.Random(profile.seed + 7)
        a, b = r.sample(range(len(movable)), 2)
        ia, ib = wb.worksheets.index(movable[a]), wb.worksheets.index(movable[b])
        wb._sheets[ia], wb._sheets[ib] = wb._sheets[ib], wb._sheets[ia]
    return mapping
