"""Transactions and payroll data (CSV, XLSX, JSON): checks the file is the right kind of table
and anonymises it column by column.

People columns (employee, payee, cardholder...) become 'Redacted Name', organisation columns
(vendor, merchant, supplier...) 'Redacted Company Name Inc'. Account, card, routing and tax
numbers, e-mails, phones and street addresses are removed. Other text cells go through the
document anonymiser (names, links, tickers).
"""
import csv
import io
import json
import re

from models.xl import REDACTED

from .anon import PERSON, TICKER  # noqa: F401  (TICKER: same markers everywhere)

PERSON_COL = re.compile(r'(^|[\s_\-])(name|employee|first|last|middle|full_?name|payee|cardholder|card_?holder|'
                        r'customer|client|recipient|beneficiary|sender|receiver|owner|approver|requester|'
                        r'nameorig|namedest|emp_?name|worker|staff)([\s_\-]|$)', re.I)
ORG_COL = re.compile(r'vendor|supplier|merchant|company|organi[sz]ation|business|counterparty|employer|bank_?name|'
                     r'contractor|payee_?business|issuer|institution', re.I)
SECRET_COL = re.compile(r'ssn|social|tax_?id|\btin\b|ein|account_?(no|num)|acct|iban|swift|routing|card_?(no|num)|'
                        r'\bpan\b|cvv|email|e-mail|phone|mobile|address|street|zip|postal|ip_?addr|device|passport|'
                        r'licen[cs]e_?(no|num)|dob|birth|identifier|employee_?id|emp_?id|badge|person_?id', re.I)
MONEY_COL = re.compile(r'amount|amt|debit|credit|payment|paid|price|value|total|balance|fee|charge|cost|expense|'
                       r'salary|pay|wage|gross|net|earnings|overtime|bonus|compensation', re.I)
PAY_COL = re.compile(r'salary|pay\b|pay_|gross|wage|earnings|overtime|bonus|compensation|regular', re.I)
TXN_COL = re.compile(r'amount|debit|credit|payment|transaction|txn|vendor|merchant|invoice|check|cheque|balance|'
                     r'charge|payout|refund|ledger|journal|account', re.I)
ORG_WORDS = re.compile(r'\b(inc|llc|ltd|corp|co|company|corporation|services|group|associates|bank|city of|county|'
                       r'department|university|hospital|systems|solutions|partners|holdings|trust|foundation|'
                       r'authority|district|school|church|lp|llp|plc|gmbh)\b\.?', re.I)


def gate(kind, header, rows):
    """None when the table belongs to kind, otherwise the reason it does not."""
    if len(rows) < 100:
        return f'too few rows ({len(rows)})'
    if len(header) < 4:
        return 'too few columns'
    h = ' '.join(header)
    if not MONEY_COL.search(h):
        return 'no money column'
    if kind == 'payroll' and not PAY_COL.search(h):
        return 'not payroll data'
    if kind == 'transactions' and not TXN_COL.search(h):
        return 'not transaction data'
    return None


def _role(col):
    if SECRET_COL.search(col):
        return 'secret'
    if ORG_COL.search(col):
        return 'org'
    if PERSON_COL.search(col) and not re.search(r'type|code|category|count|id$|_id|number|title|dept|department|office|bureau|'
                                                r'agency|unit|fund|account|job|position|program|project|division|location', col, re.I):
        return 'person'
    return 'text'


class Table:
    def __init__(self, anon):
        self.anon = anon
        self.cache = {}

    def cell(self, role, v):
        if not isinstance(v, str) or not v.strip() or not any(ch.isalpha() or ch.isdigit() for ch in v):
            return v
        if role == 'secret':
            return 'Redacted'
        if role == 'org':
            return REDACTED
        if role == 'person':
            return REDACTED if ORG_WORDS.search(v) else PERSON
        if re.fullmatch(r'[\d.,\-+$€£% ()/:]+', v):
            return v
        if v not in self.cache:
            if len(self.cache) > 200000:
                self.cache.clear()
            self.cache[v] = self.anon.scrub(v)
        return self.cache[v]

    # --- CSV ---------------------------------------------------------------
    def csv(self, src, dst, kind):
        raw = open(src, 'rb').read()
        for enc in ('utf-8-sig', 'cp1252', 'latin-1'):
            try:
                text = raw.decode(enc)
                break
            except UnicodeDecodeError:
                continue
        try:
            dialect = csv.Sniffer().sniff(text[:20000], delimiters=',;\t|')
        except csv.Error:
            dialect = csv.excel
        rows = list(csv.reader(io.StringIO(text), dialect))
        if not rows:
            return 'empty'
        header, body = rows[0], [r for r in rows[1:] if any(c.strip() for c in r)]
        why = gate(kind, header, body)
        if why:
            return why
        roles = [_role(c) for c in header]
        out = io.StringIO()
        w = csv.writer(out, lineterminator='\n')
        w.writerow([self.anon.scrub(c) for c in header])
        for r in body:
            w.writerow([self.cell(roles[i] if i < len(roles) else 'text', v) for i, v in enumerate(r)])
        open(dst, 'w', encoding='utf-8', newline='').write(out.getvalue())
        return None

    # --- XLSX --------------------------------------------------------------
    def xlsx(self, src, dst, kind):
        from openpyxl import load_workbook
        wb = load_workbook(src)
        best = None
        for ws in wb.worksheets:
            rows = list(ws.iter_rows(values_only=True))
            if not rows:
                continue
            header = [str(c or '') for c in rows[0]]
            if gate(kind, header, rows[1:]) is None:
                best = ws
            roles = [_role(c) for c in header]
            for row in ws.iter_rows(min_row=2):
                for i, c in enumerate(row):
                    if isinstance(c.value, str) and not c.value.startswith('='):
                        c.value = self.cell(roles[i] if i < len(roles) else 'text', c.value)
            for c in ws[1]:
                if isinstance(c.value, str):
                    c.value = self.anon.scrub(c.value)
            ws.title = (self.anon.scrub(ws.title).replace(REDACTED, 'Redacted Co') or 'Sheet')[:31]
        if best is None:
            return 'no transaction or payroll table'
        for ws in wb.worksheets:
            for img in list(getattr(ws, '_images', [])):
                ws._images.remove(img)
            for row in ws.iter_rows():
                for c in row:
                    c.hyperlink = None
        p = wb.properties
        p.creator = p.lastModifiedBy = PERSON
        p.title = p.subject = p.description = p.keywords = None
        wb.save(dst)
        return None

    # --- JSON (e.g. payment API fixtures) --------------------------------------
    def json(self, src, dst, kind):
        data = json.load(open(src, encoding='utf-8'))
        records = _records(data)
        if len(records) < 100:
            return f'too few records ({len(records)})'
        keys = {k for r in records[:500] for k in r}
        why = gate(kind, sorted(keys), records)
        if why:
            return why

        def walk(v, key=''):
            if isinstance(v, dict):
                return {k: walk(x, k) for k, x in v.items()}
            if isinstance(v, list):
                return [walk(x, key) for x in v]
            if isinstance(v, str):
                return self.cell(_role(key), v)
            return v
        json.dump(walk(data), open(dst, 'w', encoding='utf-8'), indent=1, ensure_ascii=False)
        return None


def _records(data):
    if isinstance(data, list):
        return [r for r in data if isinstance(r, dict)]
    if isinstance(data, dict):
        for v in data.values():
            if isinstance(v, list) and len(v) >= 10 and all(isinstance(r, dict) for r in v[:10]):
                return v
    return []
