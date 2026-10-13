"""Shared workbook conventions for every generated model.

House style: blue font = input, black = formula, green = link to another sheet. Inputs only
live on the "Historical Data" sheet (reported figures) and on input sheets (market and
transaction assumptions); every other number is a formula.
"""
from openpyxl import Workbook
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter

REDACTED = 'Redacted Company Name Inc'

NAVY = '1F3864'
BLUE_FILL = PatternFill('solid', fgColor=NAVY)
FC_FILL = PatternFill('solid', fgColor='2E75B6')
INPUT_FILL = PatternFill('solid', fgColor='FFF2CC')
HEAD = Font(bold=True, color='FFFFFF')
BOLD = Font(bold=True)
INPUT = Font(color='0000FF')
LINK = Font(color='008000')
NOTE = Font(italic=True, color='666666')
TOP = Border(top=Side(style='thin'))
NUM = '#,##0.0_);(#,##0.0);"–"_)'
NUM0 = '#,##0_);(#,##0);"–"_)'
PCT = '0.0%_);(0.0%);"–"_)'
MULT = '0.0"x"'
PRICE = '$#,##0.00'

INPUT_SHEETS = {'Historical Data', 'Market Inputs', 'Transaction Inputs', 'Scenario Inputs'}


def col(j, first=2):
    return get_column_letter(first + j)


class Sheet:
    """A statement-style sheet: labels in column A, one column per period from column B."""

    def __init__(self, wb, title, heading, periods, forecast_from=None, index=None, unit='USD millions'):
        self.ws = wb.create_sheet(title, index) if index is not None else wb.create_sheet(title)
        self.title = title
        self.rows = {}
        self.next_row = 4
        ws = self.ws
        ws['A1'] = heading
        ws['A1'].font = Font(bold=True, size=13, color=NAVY)
        ws['A2'] = unit
        ws['A2'].font = NOTE
        ws.column_dimensions['A'].width = 46
        ws.cell(row=3, column=1).fill = BLUE_FILL
        for j, p in enumerate(periods):
            c = ws.cell(row=3, column=2 + j, value=p)
            c.font, c.alignment = HEAD, Alignment(horizontal='center')
            c.fill = FC_FILL if forecast_from is not None and j >= forecast_from else BLUE_FILL
            ws.column_dimensions[col(j)].width = 13
        ws.freeze_panes = 'B4'
        ws.sheet_view.showGridLines = False

    def row(self, key, label, bold=False, gap_before=False, section=None):
        if section:
            self.next_row += 1
            c = self.ws.cell(row=self.next_row, column=1, value=section)
            c.font = Font(bold=True, color=NAVY)
            self.next_row += 1
        elif gap_before:
            self.next_row += 1
        r = self.next_row
        self.rows[key] = r
        c = self.ws.cell(row=r, column=1, value=label)
        if bold:
            c.font = BOLD
        self.next_row += 1
        return r

    def ref(self, key, j, absolute=False, external=True):
        c = col(j)
        addr = f'${c}${self.rows[key]}' if absolute else f'{c}{self.rows[key]}'
        return f"'{self.title}'!{addr}" if external else addr

    def span(self, key, j0, j1, external=True):
        a = f'{col(j0)}{self.rows[key]}:{col(j1)}{self.rows[key]}'
        return f"'{self.title}'!{a}" if external else a

    def set(self, key, j, value, fmt=NUM, bold=False, font=None):
        c = self.ws.cell(row=self.rows[key], column=2 + j, value=value)
        c.number_format = fmt
        if font is not None:
            c.font = font
        elif bold:
            c.font = BOLD
            c.border = TOP
        elif isinstance(value, str) and value.startswith('=') and "!" in value and value.count('!') == 1 \
                and value[1:].replace("'", '').split('!')[1].replace('$', '').isalnum():
            c.font = LINK
        return c


class Inputs:
    """A two-column input sheet: label, value (blue), note."""

    def __init__(self, wb, title, heading, index=None):
        self.ws = wb.create_sheet(title, index) if index is not None else wb.create_sheet(title)
        self.title = title
        self.rows = {}
        self.next_row = 4
        ws = self.ws
        ws['A1'] = heading
        ws['A1'].font = Font(bold=True, size=13, color=NAVY)
        ws['A2'] = 'Blue cells are inputs; change them to run a different case.'
        ws['A2'].font = NOTE
        ws.column_dimensions['A'].width = 44
        ws.column_dimensions['B'].width = 14
        ws.column_dimensions['C'].width = 70
        ws.sheet_view.showGridLines = False

    def section(self, text):
        self.next_row += 1
        self.ws.cell(row=self.next_row, column=1, value=text).font = Font(bold=True, color=NAVY)
        self.next_row += 1

    def add(self, key, label, value, fmt=NUM, note=None, formula=False):
        r = self.next_row
        self.rows[key] = r
        self.ws.cell(row=r, column=1, value=label)
        c = self.ws.cell(row=r, column=2, value=value)
        c.number_format = fmt
        if not formula:
            c.font, c.fill = INPUT, INPUT_FILL
        if note:
            self.ws.cell(row=r, column=3, value=note).font = NOTE
        self.next_row += 1
        return r

    def ref(self, key):
        return f"'{self.title}'!$B${self.rows[key]}"


def data_sheet(wb, heading, periods, rows, values, unit='USD millions (as reported, SEC XBRL)'):
    """The 'Historical Data' sheet: reported figures only, in blue. Returns a Sheet."""
    s = Sheet(wb, 'Historical Data', heading, periods, unit=unit)
    for key, label in rows:
        s.row(key, label)
        for j, v in enumerate(values[key]):
            s.set(key, j, v, font=INPUT)
    return s


def new_workbook():
    wb = Workbook()
    wb.remove(wb.active)
    return wb


def cover(wb, title, sector, description, sections):
    ws = wb.create_sheet('Cover', 0)
    ws.sheet_view.showGridLines = False
    ws.column_dimensions['A'].width = 3
    ws.column_dimensions['B'].width = 34
    ws.column_dimensions['C'].width = 90
    ws['B2'] = REDACTED
    ws['B2'].font = Font(bold=True, size=18, color=NAVY)
    ws['B3'] = title
    ws['B3'].font = Font(bold=True, size=13)
    ws['B4'] = f'Sector: {sector}'
    ws['B4'].font = NOTE
    ws['B6'] = 'Purpose'
    ws['B6'].font = BOLD
    ws['C6'] = description
    ws['C6'].alignment = Alignment(wrap_text=True, vertical='top')
    ws.row_dimensions[6].height = 75
    r = 8
    ws.cell(row=r, column=2, value='Contents').font = BOLD
    for name, what in sections:
        r += 1
        c = ws.cell(row=r, column=2, value=name)
        c.hyperlink = f"#'{name}'!A1"
        c.font = Font(color='0563C1', underline='single')
        ws.cell(row=r, column=3, value=what)
    r += 2
    ws.cell(row=r, column=2, value='Colour code').font = BOLD
    for label, font, fill in (('Input (hard-coded source figure or assumption)', INPUT, INPUT_FILL),
                              ('Formula', Font(color='000000'), None),
                              ('Link to another sheet', LINK, None)):
        r += 1
        c = ws.cell(row=r, column=2, value='1,234.5')
        c.font = font
        if fill:
            c.fill = fill
        ws.cell(row=r, column=3, value=label)
    r += 2
    ws.cell(row=r, column=2, value='Model checks').font = BOLD
    c = ws.cell(row=r, column=3, value="=IF(Checks!$B$3=0,\"All checks pass\",\"CHECK ERRORS - see Checks sheet\")")
    c.font = BOLD
    return ws


def checks(wb, items):
    """items: [(label, formula giving the absolute error total)]; B3 sums them."""
    ws = wb.create_sheet('Checks')
    ws.sheet_view.showGridLines = False
    ws.column_dimensions['A'].width = 60
    ws.column_dimensions['B'].width = 14
    ws['A1'] = 'Model integrity checks'
    ws['A1'].font = Font(bold=True, size=13, color=NAVY)
    ws['A3'] = 'Total check errors (must be zero)'
    ws['A3'].font = BOLD
    for i, (label, formula) in enumerate(items, start=5):
        ws.cell(row=i, column=1, value=label)
        c = ws.cell(row=i, column=2, value=f'=ROUND({formula},2)')
        c.number_format = NUM
    last = 4 + len(items)
    ws['B3'] = f'=SUMPRODUCT(ABS(B5:B{last}))'
    ws['B3'].number_format = NUM
    ws['B3'].font = BOLD
    return ws
