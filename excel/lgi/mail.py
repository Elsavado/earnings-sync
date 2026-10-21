"""E-mail exports (mbox, one file per mailbox and year) built from the records, plus an index linking every message
to the ticket, invoice, employee, sprint or month it belongs to."""
import email.utils
from email.message import EmailMessage
from pathlib import Path

import numpy as np
import pandas as pd

from .config import COMPANY, DOMAIN, FUNDING, GAMES, SEED

SUPPORT = f'support@{DOMAIN}'
FIN = f'finance@{DOMAIN}'
ALL = f'all-staff@{DOMAIN}'
BOARD = f'board@{DOMAIN}'


class Box:
    def __init__(self, root):
        self.root = Path(root)
        self.files = {}
        self.index = []
        self.n = 0

    def add(self, mailbox, when, frm, to, subject, body, related='', thread=None, reply_to=None):
        when = pd.Timestamp(when)
        self.n += 1
        mid = f'<{self.n:09d}.{when:%Y%m%d}@{DOMAIN}>'
        m = EmailMessage()
        m['Message-ID'] = mid
        m['Date'] = email.utils.format_datetime(when.tz_localize('UTC') if when.tzinfo is None else when)
        m['From'] = frm
        m['To'] = to
        m['Subject'] = subject
        if reply_to:
            m['In-Reply-To'] = reply_to
            m['References'] = reply_to
        m['X-Synthetic'] = f'Fictional record of {COMPANY}'
        m.set_content(body, cte='8bit')
        key = (mailbox, when.year)
        if key not in self.files:
            p = self.root / mailbox.split('@')[0] / f'{mailbox.split("@")[0]}-{when.year}.mbox'
            p.parent.mkdir(parents=True, exist_ok=True)
            self.files[key] = open(p, 'a', encoding='utf-8', newline='\n')
        text = m.as_string().replace('\nFrom ', '\n>From ')
        self.files[key].write(f'From {frm.split("<")[-1].rstrip(">")} {when:%a %b %d %H:%M:%S %Y}\n{text}\n')
        self.index.append({'message_id': mid, 'mailbox': mailbox, 'date': when, 'from': frm, 'to': to, 'subject': subject,
                           'thread': thread or mid, 'related_record': related})
        return mid

    def close(self):
        for f in self.files.values():
            f.close()
        return pd.DataFrame(self.index)


def support_threads(box, tickets, msgs, agents):
    em = tickets[tickets.channel == 'Email']
    if not len(em):
        return
    who = agents.set_index('employee_id')
    mm = msgs[msgs.ticket_id.isin(em.ticket_id)].sort_values(['ticket_id', 'seq'])
    t = em.set_index('ticket_id')
    last = {}
    for r in mm.itertuples():
        tk = t.loc[r.ticket_id]
        subj = f'[{r.ticket_id}] {tk.category}'
        if r.author == 'player':
            frm, to = f'{tk.first_name} <{tk.email}>', SUPPORT
        else:
            a = who.loc[r.author_id] if r.author_id in who.index else None
            frm = f'{a.first_name} {a.last_name} (Player Support) <{SUPPORT}>' if a is not None else SUPPORT
            to = f'{tk.first_name} <{tk.email}>'
        mid = box.add(SUPPORT, r.created_at, frm, to, subj if r.seq == 1 else f'Re: {subj}', r.body, r.ticket_id,
                      thread=last.get(r.ticket_id), reply_to=last.get(r.ticket_id))
        last.setdefault(r.ticket_id, mid)


def finance_mail(box, ap, emp, is_m):
    rng = np.random.default_rng(SEED + 888)
    fin = emp[emp.department == 'Finance']
    ctrl = fin.iloc[0] if len(fin) else emp.iloc[0]
    ceo = emp.iloc[0]
    for r in ap.itertuples():
        vdom = r.vendor.lower().replace(' ', '').replace('&', 'and') + '.example'
        box.add(FIN, pd.Timestamp(r.invoice_date) + pd.Timedelta(hours=int(rng.integers(8, 18))), f'{r.vendor} Billing <billing@{vdom}>', FIN,
                f'Invoice {r.invoice_id} from {r.vendor}',
                f'Hello {COMPANY} accounts payable,\n\nPlease find invoice {r.invoice_id} for {r.description}.\n'
                f'Amount due: USD {r.amount_usd:,.2f}\nDue date: {r.due_date}\n\nThank you,\n{r.vendor} Billing', r.invoice_id)
        if r.paid_date:
            box.add(FIN, pd.Timestamp(r.paid_date) + pd.Timedelta(hours=10), f'{ctrl.first_name} {ctrl.last_name} <{FIN}>',
                    f'billing@{vdom}', f'Remittance advice: {r.invoice_id}',
                    f'Hello,\n\nPayment of USD {r.amount_usd:,.2f} for invoice {r.invoice_id} was sent on {r.paid_date}.\n\n'
                    f'Regards,\n{ctrl.first_name} {ctrl.last_name}\nFinance, {COMPANY}', r.invoice_id)
    months = [c for c in is_m.columns if c not in ('section', 'line')]
    get = is_m.set_index('line')
    for mo in months:
        when = (pd.Period(mo, 'M') + 1).to_timestamp() + pd.Timedelta(days=9, hours=17)
        if when > pd.Timestamp.now():
            continue
        rev = get.loc['Total revenue', mo] if 'Total revenue' in get.index else 0
        gp = get.loc['Gross profit', mo] if 'Gross profit' in get.index else 0
        op = get.loc['Operating income (loss)', mo] if 'Operating income (loss)' in get.index else 0
        ni = get.loc['Net income (loss)', mo] if 'Net income (loss)' in get.index else 0
        box.add(FIN, when, f'{ctrl.first_name} {ctrl.last_name} <{FIN}>', BOARD, f'Monthly results {mo}',
                f'Dear board members,\n\nThe books for {mo} are closed. Summary:\n\n  Revenue            USD {rev:>14,.0f}\n'
                f'  Gross profit       USD {gp:>14,.0f}\n  Operating result   USD {op:>14,.0f}\n  Net result         USD {ni:>14,.0f}\n\n'
                f'The full statements are in the monthly pack.\n\nBest regards,\n{ctrl.first_name} {ctrl.last_name}\ncc: {ceo.first_name} {ceo.last_name}',
                f'month:{mo}')


def company_mail(box, emp, sprints, projects):
    rng = np.random.default_rng(SEED + 889)
    ceo = emp.iloc[0]
    hr = emp[emp.department == 'People & Talent']
    h = hr.iloc[0] if len(hr) else ceo
    for e in emp.itertuples():
        box.add(ALL, pd.Timestamp(e.hire_date) + pd.Timedelta(hours=9), f'{h.first_name} {h.last_name} <people@{DOMAIN}>', ALL,
                f'Please welcome {e.first_name} {e.last_name}',
                f'Hi everyone,\n\nPlease welcome {e.first_name} {e.last_name}, who joins us today as {e.title} in {e.department} '
                f'({e.location}).\n\nSay hello when you get a chance!\n\n{h.first_name}', e.employee_id)
        if e.termination_date and e.termination_reason == 'Resigned':
            box.add(ALL, pd.Timestamp(e.termination_date) + pd.Timedelta(hours=16), f'{e.first_name} {e.last_name} <{e.email}>', ALL,
                    'Thank you and goodbye', f'Hi all,\n\nToday is my last day at {COMPANY}. Thank you for everything.\n\n{e.first_name}',
                    e.employee_id)
    for when, rnd, amt in FUNDING:
        box.add(ALL, pd.Timestamp(when) + pd.Timedelta(hours=11), f'{ceo.first_name} {ceo.last_name} <{ceo.email}>', ALL,
                f'We closed our {rnd}', f'Team,\n\nI am happy to share that we closed our {rnd} of USD {amt:,.0f}. '
                f'This lets us keep building great games together.\n\n{ceo.first_name}', rnd)
    for g in GAMES:
        if g['launch'] <= pd.Timestamp.now().date():
            box.add(ALL, pd.Timestamp(g['launch']) + pd.Timedelta(hours=15), f'{ceo.first_name} {ceo.last_name} <{ceo.email}>', ALL,
                    f'{g["name"]} is live!', f'Team,\n\n{g["name"]} launched today. Thank you to everyone who made it happen.\n\n{ceo.first_name}',
                    g['code'])
    leads = projects.set_index('project_key').lead_id.to_dict()
    who = emp.set_index('employee_id')
    for s in sprints[sprints.state == 'Closed'].itertuples():
        lead = leads.get(s.project_key)
        if lead not in who.index:
            continue
        p = who.loc[lead]
        box.add(f'{s.project_key.lower()}-team@{DOMAIN}', pd.Timestamp(s.end_date) + pd.Timedelta(hours=17),
                f'{p.first_name} {p.last_name} <{p.email}>', f'{s.project_key.lower()}-team@{DOMAIN}', f'Sprint review: {s.name}',
                f'Hi team,\n\n{s.name} is closed ({s.start_date} to {s.end_date}, {s.team_size} people). '
                f'Thanks for the work this sprint; the board is updated and the next sprint starts tomorrow.\n\n{p.first_name}', s.sprint_id)
