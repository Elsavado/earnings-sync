"""Logic variants for the SEC company models (user, 2026-10-23: templates that look the same must be
"enhanced and differentiated, all with different, unique logic").

A Variant is drawn deterministically from the model's key, so one model always gets the same logic
while models of the same type differ in how they forecast: each building block (revenue, costs,
working capital, capital spending, tax, financing, payouts) has several methods, and a model also
carries its own selection of analysis modules. A method is only chosen when the company's history
supports it (for example no inventory-days method for a company without inventory).

The builders read `variant.method(block)` and `variant.has(module)`; with no variant they keep their
original single method, so other collectors are unaffected.
"""
import hashlib
import random

THREE = {
    'revenue': ['fade', 'decay', 'stepdown', 'cagr', 'price_volume', 'scenario_weighted'],
    'costs': ['pct', 'fixed_variable', 'margin_target', 'opex_leverage'],
    'working_capital': ['pct_avg', 'days_converge', 'last_ratio'],
    'capex': ['pct', 'maintenance_growth', 'useful_life', 'intensity_fade'],
    'tax': ['effective', 'nol', 'statutory_blend'],
    'financing': ['hold', 'amortise', 'target_leverage'],
    'payout': ['payout', 'dps_growth', 'payout_target'],
    'interest': ['historical', 'rate_curve'],
}
THREE_MODULES = ['dupont', 'cash_conversion', 'piotroski', 'scenario_manager', 'breakeven', 'roic_tree', 'growth_bridge']
HORIZONS = [4, 5, 5, 6, 7, 8]


# Uniqueness (user, 2026-10-24: "the models being built should each have unique logic"): every Variant made while a
# model is built is recorded, and signature() names the model's full logic (each module's methods and modules, the
# forecast horizon). A collector that finds a signature already used re-draws with reset(salt) until it is new.
SALT = 0
CREATED = []


def reset(salt=0):
    """Start a model build: forget earlier variants; salt > 0 re-draws every choice (same key, different logic)."""
    global SALT
    SALT = salt
    CREATED.clear()


def signature():
    """Stable id of the logic of the model built since reset() (methods and modules of every part, not the data)."""
    parts = []
    for i, v in enumerate(CREATED):
        part = v.key.rsplit(':', 1)[-1] if i else 'core'
        mods = ','.join(sorted(m for m in v.modules if not m.startswith('_x')))
        meth = ','.join(f'{b}={m}' for b, m in sorted(v.methods.items()))
        parts.append(f'{part}|{meth}|{mods}' + (f'|y{v.years}' if not i else ''))
    return hashlib.sha1(';'.join(parts).encode()).hexdigest()[:20] if parts else None


# The most common default of each block says little about a model, so a name tag prefers the other choices.
TAG_SKIP = {'pct', 'hold', 'historical', 'effective', 'payout', 'marginal', 'market', 'mid_year', 'flat', 'partial',
            'full_deduction', 'functional', 'prior_year', 'revolver_light', 'pct_avg', 'seasonal', 'investment_grade'}


TAG_NAMES = {
    'cagr': 'CAGR Growth', 'decay': 'Decay Growth', 'fade': 'Fade Growth', 'stepdown': 'Step-Down Growth',
    'price_volume': 'Price x Volume', 'scenario_weighted': 'Probability-Weighted', 'fixed_variable': 'Fixed-Variable Costs',
    'margin_target': 'Margin Reversion', 'opex_leverage': 'Operating Leverage', 'days_converge': 'Working-Capital Days',
    'last_ratio': 'Latest Ratios', 'maintenance_growth': 'Maintenance + Growth Capex', 'useful_life': 'Useful-Life D&A',
    'intensity_fade': 'Capex Fade', 'nol': 'Tax Losses', 'statutory_blend': 'Statutory Tax', 'amortise': 'Amortising Debt',
    'target_leverage': 'Target Leverage', 'dps_growth': 'Dividend Growth', 'payout_target': 'Payout Target',
    'rate_curve': 'Repricing Debt', 'capm': 'CAPM', 'capm_size': 'Size Premium', 'adjusted_beta': 'Blume Beta',
    'target': 'Target Weights', 'book': 'Book Weights', 'blended': 'Blended Tax', 'midpoint': 'Midpoint TV',
    'perpetuity_led': 'Perpetuity-Led', 'exit_led': 'Exit-Led', 'value_driver': 'Value Driver', 'end_year': 'Year-End Discounting',
    'tlb_notes': 'TLB + Notes', 'unitranche': 'Unitranche', 'tlb_pik': 'PIK Mezzanine', 'cash_build': 'Cash Build',
    'contraction': 'Multiple Contraction', 'mean_reversion': 'Multiple Reversion', 'interest_cap': 'Interest Cap',
    'even': 'Even Phasing', 'ramp': 'Ramp Phasing', 'commercial': 'Commercial Structure', 'product_led': 'Product-Led',
    'flexed': 'Flexed Budget', 'leveraged': 'Leveraged Covenants', 'bank_style': 'Bank Covenants', 'ffo_debt': 'FFO/Debt Rating',
    'ebit_coverage': 'Coverage Rating', 'revolver_heavy': 'Large Revolver',
}


def tag(limit=2):
    """A short name for the logic of the model built since reset(), e.g. 'Value Driver, Decay' (module first, then core)."""
    picks = []
    for v in reversed(CREATED):
        for m in v.methods.values():
            if m not in TAG_SKIP and len(picks) < limit:
                picks.append(TAG_NAMES.get(m) or m.replace('_', ' ').title())
                break
    return ', '.join(picks) or 'Base Methods'


class Variant:
    def __init__(self, key, blocks=THREE, modules=THREE_MODULES, horizons=HORIZONS, allowed=None):
        """allowed(block, method) -> bool lets the builder rule out methods the data cannot support."""
        self.key = key
        self.seed = int(hashlib.sha256((f'variant:{key}' + (f':salt{SALT}' if SALT else '')).encode()).hexdigest()[:16], 16)
        r = self.rng = random.Random(self.seed)
        CREATED.append(self)
        self.methods = {}
        for block, options in blocks.items():
            ok = [m for m in options if allowed is None or allowed(block, m)] or options[:1]
            self.methods[block] = r.choice(ok)
        k = r.choice([2, 3, 3, 4])
        self.modules = set(r.sample(modules, min(k, len(modules))))
        self.years = r.choice(horizons)
        # parameter draws, so even two models with the same methods use different settings
        self.params = {
            'decay': round(r.uniform(0.55, 0.85), 2),
            'step_years': r.choice([1, 2, 2, 3]),
            'inflation': round(r.uniform(0.018, 0.032), 4),
            'scenario_p': r.choice([(0.6, 0.2, 0.2), (0.5, 0.25, 0.25), (0.7, 0.15, 0.15), (0.55, 0.2, 0.25)]),
            'scenario_spread': round(r.uniform(0.02, 0.05), 3),
            'elasticity': round(r.uniform(0.55, 0.9), 2),
            'maint_factor': round(r.uniform(0.85, 1.15), 2),
            'amort': round(r.uniform(0.04, 0.15), 3),
            'statutory': r.choice([0.21, 0.21, 0.23, 0.25]),
            'dps_growth': round(r.uniform(0.02, 0.08), 3),
            'payout_target': round(r.uniform(0.2, 0.5), 2),
            'spread': round(r.uniform(0.015, 0.04), 4),
            'rf': round(r.uniform(0.038, 0.046), 4),
        }

    def method(self, block):
        return self.methods.get(block)

    def has(self, module):
        return module in self.modules

    def describe(self):
        """One line per choice, for the model's cover / methodology note."""
        return [f'{b.replace("_", " ").capitalize()}: {m.replace("_", " ")}' for b, m in self.methods.items()]
