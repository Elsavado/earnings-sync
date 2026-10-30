"""YouTube: company (see youtube.py)."""
from . import youtube


def items(ctx, log):
    return youtube.items(ctx, log, 'company')
