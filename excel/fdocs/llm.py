"""Optional LLM acceptance check next to the keyword topic filter (topic.py), for the office and research kinds.

Before a candidate is made into a file, claude-haiku-5-5 is asked whether the material is finance, accounting,
hedge-fund or financial-analysis content (office kinds: also English, and from the US or Canada). A no rejects it.
Candidates the keyword filter would reject although they carry finance signals ('weak' candidates) are kept only
when the model says yes, so the queues do not run dry on keyword misses.

Only the title and the first EXCERPT characters are sent. Without ANTHROPIC_API_KEY (or the anthropic package) the
check is off and the keyword filter decides alone, as before. Spend is capped: TOPIC_BUDGET_USD (default 10) for
both collectors together, shared out per job (TOPIC_BUDGET_SHARE jobs, default 7: five office types and two
research types); the job's running total is kept in its state, and once its share is spent the keywords decide.
Cost is counted from response.usage at $0.10 / $0.50 per million input / output tokens. The key is read by the SDK
from the environment and never logged.
"""
import json
import os

MODEL = 'claude-haiku-5-5'
PRICE_IN, PRICE_OUT = 0.10 / 1e6, 0.50 / 1e6
EXCERPT = 3000
KINDS = ('gsheets', 'gdocs', 'slides', 'presentations', 'bookkeeping', 'scinotebooks', 'figma')
OFFICE = ('gsheets', 'gdocs', 'slides', 'presentations', 'bookkeeping')
WHAT = {'gsheets': 'a spreadsheet', 'gdocs': 'a document', 'slides': 'a slide deck', 'presentations': 'a presentation',
        'bookkeeping': 'a bookkeeping table', 'scinotebooks': 'a Jupyter notebook',
        'figma': 'a Figma design with its HTML/CSS'}
SYSTEM = ('You check material for a collection that holds finance content only: finance, accounting, bookkeeping, '
          'budgets and public finance, auditing, tax, banking, insurance, investing, trading, hedge funds, '
          'quantitative finance and financial analysis. Material that only mentions money in passing (a research '
          'grant, a price in a science paper, the budget of an unrelated project) is not finance content. '
          'Answer with the JSON schema only.')
SCHEMA = {
    'type': 'object',
    'properties': {
        'finance': {'type': 'boolean', 'description': 'The material is mainly about finance as defined.'},
        'english': {'type': 'boolean', 'description': 'The material is written in English.'},
        'us_or_canada': {'type': 'string', 'enum': ['yes', 'no', 'unclear'],
                         'description': 'It comes from, or is about, the United States or Canada.'},
    },
    'required': ['finance', 'english', 'us_or_canada'],
    'additionalProperties': False,
}
_client = None


def _budget():
    try:
        total = float(os.environ.get('TOPIC_BUDGET_USD') or 10)
        share = max(1, int(os.environ.get('TOPIC_BUDGET_SHARE') or 7))
    except ValueError:
        total, share = 10.0, 7
    return total / share


def _stats(state):
    return state.setdefault('llm', {'usd': 0.0, 'calls': 0, 'yes': 0, 'no': 0, 'errors': 0})


def available(state=None):
    """The check can run: a key is set, the SDK is installed and (with state) this job's share is not spent."""
    if not os.environ.get('ANTHROPIC_API_KEY'):
        return False
    try:
        import anthropic  # noqa: F401
    except ImportError:
        return False
    return state is None or _stats(state)['usd'] < _budget()


def _get_client():
    global _client
    if _client is None:
        import anthropic
        _client = anthropic.Anthropic(timeout=60.0, max_retries=2)  # the key comes from the environment
    return _client


def judge(state, kind, title, excerpt):
    """True (accept), False (reject) or None (no check: no key, share spent, or the call failed)."""
    if kind not in KINDS or not available(state):
        return None
    st = _stats(state)
    office = kind in OFFICE
    prompt = (f'Material: {WHAT.get(kind, "a file")}.\nTitle: {(title or "(none)")[:300]}\n'
              f'Beginning of the content:\n"""\n{(excerpt or "")[:EXCERPT]}\n"""\n'
              'Is it finance content as defined? Is it in English? Does it come from the US or Canada?')
    try:
        r = _get_client().messages.create(
            model=MODEL, max_tokens=1024, system=SYSTEM,
            messages=[{'role': 'user', 'content': prompt}],
            output_config={'effort': 'low', 'format': {'type': 'json_schema', 'schema': SCHEMA}})
        st['usd'] += r.usage.input_tokens * PRICE_IN + r.usage.output_tokens * PRICE_OUT
        st['calls'] += 1
        if r.stop_reason == 'refusal':
            raise ValueError('refusal')
        data = json.loads(next(b.text for b in r.content if b.type == 'text'))
    except Exception:  # noqa: BLE001  (network, API or parsing: the keyword filter decides)
        st['errors'] += 1
        return None
    ok = bool(data.get('finance')) and (not office or (bool(data.get('english')) and data.get('us_or_canada') != 'no'))
    st['yes' if ok else 'no'] += 1
    return ok


def summary(state, start=None):
    """'LLM check: N calls (a accepted, r rejected, e failed), $x this run, $y of $z for this job'."""
    st = _stats(state)
    s0 = start or {}
    run = {k: st[k] - s0.get(k, 0) for k in ('calls', 'yes', 'no', 'errors', 'usd')}
    return (f'LLM check ({MODEL}): {run["calls"]} calls this run ({run["yes"]} accepted, {run["no"]} rejected, '
            f'{run["errors"]} failed), ${run["usd"]:.4f} this run, ${st["usd"]:.4f} of ${_budget():.2f} for this job')
