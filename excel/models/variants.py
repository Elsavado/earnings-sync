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


class Variant:
    def __init__(self, key, blocks=THREE, modules=THREE_MODULES, horizons=HORIZONS, allowed=None):
        """allowed(block, method) -> bool lets the builder rule out methods the data cannot support."""
        self.key = key
        self.seed = int(hashlib.sha256(f'variant:{key}'.encode()).hexdigest()[:16], 16)
        r = self.rng = random.Random(self.seed)
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
