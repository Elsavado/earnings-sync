"""Market inputs for valuation and LBO models, fetched once per run.

- US 10-year Treasury yield and SOFR: FRED (no key needed).
- Implied equity risk premium and industry unlevered betas: Aswath Damodaran's public data sets.
Each value carries a source note that is written next to it on the model's input sheet.
"""
import csv
import io

import requests

UA = {'User-Agent': 'excel-models/1.0 (research; contact via repository)'}
DAMODARAN = 'https://pages.stern.nyu.edu/~adamodar/pc/datasets/'

# SIC code ranges -> Damodaran industry name (first match wins).
SIC_INDUSTRY = [
    ((100, 999), 'Farming/Agriculture'), ((1000, 1039), 'Metals & Mining'), ((1040, 1049), 'Precious Metals'),
    ((1050, 1099), 'Metals & Mining'), ((1200, 1299), 'Coal & Related Energy'),
    ((1310, 1319), 'Oil/Gas (Production and Exploration)'), ((1380, 1389), 'Oilfield Svcs/Equip.'),
    ((1400, 1499), 'Metals & Mining'), ((1520, 1531), 'Homebuilding'), ((1540, 1799), 'Engineering/Construction'),
    ((2000, 2079), 'Food Processing'), ((2080, 2085), 'Beverage (Alcoholic)'), ((2086, 2087), 'Beverage (Soft)'),
    ((2090, 2099), 'Food Processing'), ((2100, 2199), 'Tobacco'), ((2200, 2399), 'Apparel'),
    ((2400, 2499), 'Paper/Forest Products'), ((2500, 2599), 'Furn/Home Furnishings'), ((2600, 2699), 'Paper/Forest Products'),
    ((2700, 2799), 'Publishing & Newspapers'), ((2800, 2829), 'Chemical (Basic)'), ((2836, 2836), 'Drugs (Biotechnology)'), ((2830, 2835), 'Drugs (Pharmaceutical)'),
    ((2840, 2844), 'Household Products'), ((2850, 2899), 'Chemical (Specialty)'),
    ((2900, 2999), 'Oil/Gas (Integrated)'), ((3000, 3099), 'Rubber& Tires'), ((3100, 3199), 'Shoe'),
    ((3200, 3299), 'Building Materials'), ((3300, 3329), 'Steel'), ((3330, 3399), 'Metals & Mining'),
    ((3400, 3499), 'Machinery'), ((3500, 3569), 'Machinery'), ((3570, 3579), 'Computers/Peripherals'),
    ((3580, 3599), 'Machinery'), ((3600, 3629), 'Electrical Equipment'), ((3630, 3659), 'Electronics (Consumer & Office)'),
    ((3660, 3669), 'Telecom. Equipment'), ((3670, 3679), 'Semiconductor'), ((3680, 3699), 'Electronics (General)'),
    ((3700, 3713), 'Auto & Truck'), ((3714, 3714), 'Auto Parts'), ((3715, 3719), 'Auto & Truck'),
    ((3720, 3729), 'Aerospace/Defense'), ((3730, 3739), 'Shipbuilding & Marine'), ((3740, 3799), 'Transportation'),
    ((3812, 3812), 'Aerospace/Defense'), ((3800, 3811), 'Electronics (General)'), ((3813, 3849), 'Healthcare Products'), ((3850, 3899), 'Healthcare Products'),
    ((3900, 3999), 'Recreation'), ((4000, 4099), 'Transportation (Railroads)'), ((4100, 4199), 'Transportation'),
    ((4200, 4299), 'Trucking'), ((4400, 4499), 'Shipbuilding & Marine'), ((4500, 4599), 'Air Transport'),
    ((4600, 4699), 'Oil/Gas Distribution'), ((4700, 4799), 'Transportation'), ((4800, 4812), 'Telecom (Wireless)'),
    ((4813, 4829), 'Telecom. Services'), ((4830, 4839), 'Broadcasting'), ((4840, 4849), 'Cable TV'),
    ((4850, 4899), 'Telecom. Services'), ((4900, 4919), 'Power'), ((4920, 4929), 'Oil/Gas Distribution'),
    ((4930, 4939), 'Utility (General)'), ((4940, 4949), 'Utility (Water)'), ((4950, 4959), 'Environmental & Waste Services'),
    ((4960, 4999), 'Utility (General)'), ((5000, 5139), 'Retail (Distributors)'), ((5140, 5149), 'Food Wholesalers'),
    ((5150, 5199), 'Retail (Distributors)'), ((5200, 5299), 'Retail (Building Supply)'), ((5300, 5399), 'Retail (General)'),
    ((5400, 5499), 'Retail (Grocery and Food)'), ((5500, 5599), 'Retail (Automotive)'), ((5600, 5699), 'Apparel'),
    ((5700, 5799), 'Retail (Special Lines)'), ((5800, 5899), 'Restaurant/Dining'), ((5900, 5999), 'Retail (Special Lines)'),
    ((6000, 6019), 'Bank (Money Center)'), ((6020, 6029), 'Banks (Regional)'), ((6030, 6099), 'Banks (Regional)'),
    ((6100, 6199), 'Financial Svcs. (Non-bank & Insurance)'), ((6200, 6299), 'Brokerage & Investment Banking'),
    ((6310, 6319), 'Insurance (Life)'), ((6320, 6329), 'Insurance (General)'), ((6330, 6339), 'Insurance (Prop/Cas.)'),
    ((6350, 6399), 'Insurance (General)'), ((6400, 6499), 'Insurance (General)'),
    ((6500, 6549), 'Real Estate (Operations & Services)'), ((6550, 6559), 'Real Estate (Development)'),
    ((6700, 6797), 'Investments & Asset Management'), ((6798, 6798), 'R.E.I.T.'), ((6799, 6799), 'Investments & Asset Management'),
    ((7000, 7099), 'Hotel/Gaming'), ((7200, 7299), 'Business & Consumer Services'), ((7300, 7319), 'Advertising'),
    ((7320, 7369), 'Business & Consumer Services'), ((7370, 7371), 'Computer Services'), ((7372, 7372), 'Software (System & Application)'),
    ((7373, 7373), 'Computer Services'), ((7374, 7374), 'Information Services'), ((7375, 7379), 'Software (Internet)'),
    ((7380, 7399), 'Business & Consumer Services'), ((7500, 7599), 'Business & Consumer Services'),
    ((7800, 7899), 'Entertainment'), ((7900, 7999), 'Recreation'), ((8000, 8059), 'Healthcare Support Services'),
    ((8060, 8069), 'Hospitals/Healthcare Facilities'), ((8070, 8099), 'Healthcare Support Services'),
    ((8200, 8299), 'Education'), ((8700, 8711), 'Engineering/Construction'), ((8712, 8799), 'Business & Consumer Services'),
    ((9000, 9999), 'Diversified'),
]
DEFAULT_INDUSTRY = 'Total Market (without financials)'


def industry_for(sic):
    try:
        s = int(sic)
    except (TypeError, ValueError):
        return DEFAULT_INDUSTRY
    for (lo, hi), name in SIC_INDUSTRY:
        if lo <= s <= hi:
            return name
    return DEFAULT_INDUSTRY


def _fred(series):
    r = requests.get(f'https://fred.stlouisfed.org/graph/fredgraph.csv?id={series}', headers=UA, timeout=20)
    r.raise_for_status()
    rows = [row for row in csv.reader(io.StringIO(r.text))][1:]
    for d, v in reversed(rows):
        try:
            return float(v) / 100, d
        except ValueError:
            continue
    raise ValueError(f'no value in FRED {series}')


def _treasury_10y():
    import datetime
    year = datetime.date.today().year
    for y in (year, year - 1):
        url = ('https://home.treasury.gov/resource-center/data-chart-center/interest-rates/daily-treasury-rates.csv/'
               f'{y}/all?type=daily_treasury_yield_curve&field_tdr_date_value={y}&page&_format=csv')
        r = requests.get(url, headers=UA, timeout=60)
        rows = list(csv.reader(io.StringIO(r.text)))
        if len(rows) > 1 and '10 Yr' in rows[0]:
            k = rows[0].index('10 Yr')
            return float(rows[1][k]) / 100, rows[1][0]
    raise ValueError('no Treasury yield')


def _nyfed_sofr():
    r = requests.get('https://markets.newyorkfed.org/api/rates/secured/sofr/last/1.json', headers=UA, timeout=60)
    rate = r.json()['refRates'][0]
    return rate['percentRate'] / 100, rate['effectiveDate']


def _xls(name):
    import xlrd
    r = requests.get(DAMODARAN + name, headers=UA, timeout=120)
    r.raise_for_status()
    return xlrd.open_workbook(file_contents=r.content)


class Market:
    """Holds the run's market inputs; falls back to documented defaults if a source is down."""

    def __init__(self, log=print):
        self.notes = {}
        for fn, note in ((_treasury_10y, 'US 10-year Treasury par yield, U.S. Treasury daily yield curve, {}'),
                         (lambda: _fred('DGS10'), 'US 10-year Treasury constant-maturity yield, FRED DGS10, {}')):
            try:
                self.rf, d = fn()
                self.notes['rf'] = note.format(d)
                break
            except Exception as err:  # noqa: BLE001
                log(f'market: risk-free source failed ({err})')
        else:
            self.rf, self.notes['rf'] = 0.0425, 'Fallback value (rate feeds unavailable); update to the current 10-year Treasury yield'
        for fn, note in ((_nyfed_sofr, 'Secured Overnight Financing Rate, Federal Reserve Bank of New York, {}'),
                         (lambda: _fred('SOFR'), 'Secured Overnight Financing Rate, FRED SOFR, {}')):
            try:
                self.sofr, d = fn()
                self.notes['sofr'] = note.format(d)
                break
            except Exception as err:  # noqa: BLE001
                log(f'market: SOFR source failed ({err})')
        else:
            self.sofr, self.notes['sofr'] = 0.04, 'Fallback value (rate feeds unavailable); update to current SOFR'
        try:
            sh = _xls('histimpl.xls').sheets()[0]
            year, erp, cidx = None, None, None
            for r in range(sh.nrows):
                row = sh.row_values(r)
                if cidx is None:
                    for k, v in enumerate(row):
                        if isinstance(v, str) and v.strip().lower() == 'implied erp (fcfe)':
                            cidx = k
                    continue
                if isinstance(row[0], float) and 1900 < row[0] < 2200 and isinstance(row[cidx], float):
                    year, erp = int(row[0]), row[cidx]
            if erp is None:
                raise ValueError('implied ERP column not found')
            self.erp = erp
            self.notes['erp'] = f'Implied equity risk premium (FCFE-based), end of {year}, A. Damodaran histimpl.xls'
        except Exception as err:  # noqa: BLE001
            self.erp, self.notes['erp'] = 0.045, 'Fallback value (Damodaran data unavailable); update to a current implied ERP'
            log(f'market: ERP fallback ({err})')
        self.betas = {}
        try:
            sh = _xls('betas.xls').sheet_by_name('Industry Averages')
            for r in range(sh.nrows):
                row = sh.row_values(r)
                if isinstance(row[0], str) and isinstance(row[5], float) and isinstance(row[3], float):
                    self.betas[row[0].strip()] = {'unlevered': row[7] if isinstance(row[7], float) else row[5],
                                                  'de': row[3], 'n': row[1]}
        except Exception as err:  # noqa: BLE001
            log(f'market: industry betas unavailable ({err})')

    def beta(self, sic):
        name = industry_for(sic)
        b = self.betas.get(name) or self.betas.get(DEFAULT_INDUSTRY)
        if b:
            return b['unlevered'], b['de'], name, f'Unlevered beta corrected for cash, {name} ({int(b["n"])} US firms), A. Damodaran betas.xls'
        return 1.0, 0.25, name, 'Fallback unlevered beta of 1.0 (Damodaran data unavailable)'
