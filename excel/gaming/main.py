"""python -m gaming.main KIND [KIND ...]

Kinds: catalog, details, reviews, news, prices, players, players_daily, mobile, hardware, companies, benchmarks.
Environment: SHARED_DRIVE_ID, GOOGLE_* sign-in, DRY_RUN (writes ./samples with small limits)."""
import sys
import traceback
from datetime import datetime, timedelta, timezone

from . import derived, mobile, sec, steam
from .out import Out, dry_run, log


def main():
    dry = dry_run()
    out = Out(dry)
    n = 40 if dry else None
    jobs = {
        'catalog': lambda: steam.catalog(out, limit_pages=1 if dry else None),
        'details': lambda: steam.details(out, n or 5000),
        'reviews': lambda: steam.reviews(out, n or 5000),
        'news': lambda: steam.news(out, n or 5000),
        'prices': lambda: steam.prices(out, n or 5000),
        'players': lambda: steam.players(out, n or 2000),
        'players_daily': lambda: steam.players_daily(out, (datetime.now(timezone.utc) - timedelta(days=1)).strftime('%Y-%m-%d')),
        'mobile': lambda: mobile.mobile(out),
        'hardware': lambda: steam.hardware(out, backfill=not dry),
        'companies': lambda: sec.companies(out, only=['Roblox', 'Playtika'] if dry else None),
        'benchmarks': lambda: derived.benchmarks(out),
    }
    failed = []
    for kind in sys.argv[1:]:
        log(f'== {kind}')
        try:
            jobs[kind]()
        except Exception:  # noqa: BLE001 - the other kinds still run
            traceback.print_exc()
            failed.append(kind)
    if failed:
        sys.exit(f'failed: {failed}')


if __name__ == '__main__':
    main()
