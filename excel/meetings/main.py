"""One run of the "Meeting Recordings" collector for one source.

SOURCE = corpora (AMI, ICSI, Earnings-21) | fed (Federal Reserve press conferences and open Board meetings) |
granicus (city/county budget and finance committees on Granicus) | archive (Creative Commons meetings on the
Internet Archive) | ytpublic (public bodies on YouTube) | ytcompany (company investor days and webinars on YouTube)
| ytcc (Creative Commons YouTube uploads).

Each recording becomes one folder: audio.m4a (mono 64 kbps AAC), transcript.vtt, transcript.txt (timestamped) and
meta.json. Transcripts: the official one when the source has it, else uploaded captions, else YouTube
auto-captions, else faster-whisper on the runner. Environment: GOOGLE_* (Drive), SHARED_DRIVE_ID, LIVE, RUN_MINUTES,
MAX_ITEMS (0 = no limit), YT_COOKIES_FILE (optional). Never exits with an error (the user wants no failure e-mails):
problems are logged, the saved state carries over.
"""
import datetime
import importlib
import json
import os
import re
import shutil
import sys
import tempfile
import time
import traceback
from pathlib import Path

from . import media
from .drive import Drive

START = time.time()
SOURCE = os.environ.get('SOURCE', '')
BUDGET = float(os.environ.get('RUN_MINUTES', '320')) * 60
MAX_ITEMS = int(os.environ.get('MAX_ITEMS') or 0)
SOURCES = ('corpora', 'fed', 'granicus', 'archive', 'ytpublic', 'ytcompany', 'ytcc')
TYPES = {'public': 'Public Finance Meetings', 'company': 'Company Webinars and Investor Days',
         'corpora': 'Open Meeting Corpora', 'cc': 'Creative Commons Uploads'}
HOW = {'official': 'official transcript', 'captions': 'captions uploaded by the publisher',
       'auto-captions': 'YouTube automatic captions', 'asr': 'speech recognition on the runner (faster-whisper)'}
MAX_FAILS = 3


def log(msg):
    print(f'[{time.strftime("%H:%M:%S")}] {msg}', flush=True)


def clean(s, n=110):
    s = re.sub(r'[\\/:*?"<>|\x00-\x1f]+', ' ', str(s or '')).strip()
    s = re.sub(r'\s+', ' ', s).strip(' .')
    return s[:n].rstrip(' .') or 'Untitled'


class Ctx:
    def __init__(self, source):
        self.source = source
        self.drive = Drive(source)
        self.state_name = f'state-{source}.json.gz'
        self.state = self.drive.load(self.state_name)
        self.state.setdefault('failed', {})
        self.state.setdefault('skipped', {})
        self.done = self.drive.uploaded()
        self.asr = media.ASR(log)
        self.stats = {'collected': 0, 'already': 0, 'filtered': 0, 'blocked': 0, 'failed': 0, 'deferred': 0}
        self.how = {}
        self.licences = {}
        self.yt_ok = self.yt_blocked = 0
        self.yt_dead = False
        self.http = media.session()

    def left(self):
        return BUDGET - (time.time() - START)

    def save(self):
        self.state['items'] = self.state.get('items', 0) + self.drive.sent_items
        self.state['bytes'] = self.state.get('bytes', 0) + self.drive.sent_bytes
        self.state['recordings'] = self.state.get('recordings', 0) + self.stats['collected'] - self.state.get('_c', 0)
        self.state['_c'] = self.stats['collected']
        self.drive.sent_items = self.drive.sent_bytes = 0
        self.drive.save(self.state_name, self.state)


def process(ctx, it):
    """Collects one recording. Returns 'collected' | 'already'; raises media.Skip, media.Blocked, media.OutOfTime or errors."""
    rid = media.rec_id(ctx.source, it['id'])
    if f'{rid}/meta.json' in ctx.done:
        return 'already'
    work = Path(tempfile.mkdtemp(prefix='mt_'))
    try:
        meta = {'title': it.get('title'), 'source_url': it.get('url'), 'organisation': it.get('org'),
                'date': it.get('date') or '', 'duration_seconds': None, 'licence': it.get('licence'),
                'licence_url': it.get('licence_url'), 'source_type': TYPES[it['type']], 'collection': ctx.source,
                'language': 'en'}
        meta.update(it.get('meta') or {})
        segs, how, detail = None, None, ''
        if it.get('segments'):
            segs = it['segments']()
            how, detail = 'official', it.get('segments_how', '')
        if not it['media']:
            raise media.Skip('no audio or video file')
        src, err = None, None
        for kind, url in it['media']:
            try:
                if kind == 'ytdlp':
                    if 'youtube.com' in url or 'youtu.be' in url:
                        if ctx.yt_dead:
                            raise media.Blocked('YouTube blocked earlier in this run')
                    try:
                        info, src, ysegs, yhow = media.ytdlp_get(url, work, it.get('check'))
                    except media.Blocked:
                        if 'youtube' in url:
                            ctx.yt_blocked += 1
                            if ctx.yt_blocked >= 6 and ctx.yt_ok == 0:
                                ctx.yt_dead = True
                                log('YouTube refuses this runner (bot check) on every video so far: stopping YouTube '
                                    'downloads for this run')
                        raise
                    if 'youtube' in url:
                        ctx.yt_ok += 1
                    upd = it.get('from_info')(info) if it.get('from_info') else {}
                    meta.update({k: v for k, v in upd.items() if v})
                    if not segs and ysegs:
                        segs, how = ysegs, yhow
                        detail = 'English captions uploaded with the video' if yhow == 'captions' else \
                            'YouTube automatic English captions (yt-dlp --write-auto-subs)'
                elif kind == 'direct':
                    ext = re.sub(r'[^a-z0-9]', '', url.split('?')[0].rsplit('.', 1)[-1].lower())[:5] or 'bin'
                    src = work / f'src.{ext}'
                    media.fetch(ctx.http, url, src)
                else:  # stream: ffmpeg reads the address itself
                    src = url
                break
            except (media.Skip, media.Blocked, media.OutOfTime):
                raise
            except Exception as e:  # noqa: BLE001 - try the next way to the same recording
                err = e
                src = None
        if src is None:
            raise err or RuntimeError('no media')
        audio = work / 'audio.m4a'
        secs = media.to_audio(src, audio)
        if secs < 30:
            raise RuntimeError(f'audio only {secs:.0f} s long')
        if not isinstance(src, str):
            Path(src).unlink(missing_ok=True)
        meta['duration_seconds'] = round(secs, 1)
        if not segs and it.get('captions_url'):
            try:
                r = ctx.http.get(it['captions_url'], timeout=60)
                if r.ok and '-->' in r.text:
                    segs = media.parse_captions(r.text)
                    how, detail = 'captions', it.get('captions_how', 'captions published with the recording')
            except Exception:  # noqa: BLE001
                segs = None
        if not segs:
            need = ctx.asr.estimate(secs)
            if ctx.left() < need + 600:
                raise media.OutOfTime(f'speech recognition of {secs / 60:.0f} min would need ~{need / 60:.0f} min')
            segs = ctx.asr.run(audio, secs)
            how, detail = 'asr', f'faster-whisper {ctx.asr.name} (int8, CPU), English'
        if not segs:
            raise RuntimeError('no speech found')
        names = media.write_transcript(segs, work)
        meta.update({'transcript_method': how, 'transcript_detail': detail or HOW[how],
                     'transcript_segments': len(segs), 'audio': 'audio.m4a (AAC mono 64 kbps)',
                     'collected_utc': datetime.datetime.now(datetime.timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ'),
                     'record_id': rid})
        extras = []
        for name, url in it.get('extra_files', []):
            try:
                media.fetch(ctx.http, url, work / name)
                extras.append(name)
            except Exception:  # noqa: BLE001 - extras are optional
                pass
        meta['files'] = ['audio.m4a', *names, *extras, 'meta.json']
        Path(work, 'meta.json').write_text(json.dumps(meta, indent=2, ensure_ascii=False), encoding='utf-8')
        date = (meta.get('date') or '')[:10]
        rel = f"{TYPES[it['type']]}/{clean(it.get('group') or meta.get('organisation'), 80)}/" \
              f"{clean(((date + ' ') if date else '') + (meta.get('title') or it['id']))}"
        for name in meta['files']:
            key = f'{rid}/{name}'
            if key not in ctx.done:
                ctx.done[key] = ctx.drive.upload(work / name, rel, name, key)
        ctx.how[how] = ctx.how.get(how, 0) + 1
        ctx.licences[meta.get('licence')] = ctx.licences.get(meta.get('licence'), 0) + 1
        log(f'  + {rel} ({secs / 60:.0f} min, transcript: {how})')
        return 'collected'
    finally:
        shutil.rmtree(work, ignore_errors=True)


def collect(ctx, items):
    n = 0
    for it in items:
        if ctx.left() < 15 * 60:
            log('time budget reached')
            break
        if MAX_ITEMS and ctx.stats['collected'] >= MAX_ITEMS:
            log(f'MAX_ITEMS={MAX_ITEMS} reached')
            break
        fid = it['id']
        if ctx.state['failed'].get(fid, 0) >= MAX_FAILS or fid in ctx.state['skipped']:
            continue
        try:
            res = process(ctx, it)
            ctx.stats[res] += 1
        except media.Skip as e:
            ctx.stats['filtered'] += 1
            ctx.state['skipped'][fid] = str(e)[:80]
        except media.Blocked as e:
            ctx.stats['blocked'] += 1
            if not ctx.yt_dead:
                log(f'  blocked: {it.get("title")!r}: {str(e)[:160]}')
        except media.OutOfTime as e:
            ctx.stats['deferred'] += 1
            log(f'  deferred to a later run: {it.get("title")!r}: {e}')
        except Exception as e:  # noqa: BLE001 - logged; counted; retried on later runs
            ctx.stats['failed'] += 1
            ctx.state['failed'][fid] = ctx.state['failed'].get(fid, 0) + 1
            log(f'  failed: {it.get("title")!r}: {type(e).__name__}: {str(e)[:300]}\n'
                + ''.join(traceback.format_exc().splitlines(True)[-6:]))
        n += 1
        if n % 5 == 0:
            ctx.save()
        if ctx.yt_dead and it.get('youtube_only'):
            break


def main():
    if SOURCE not in SOURCES:
        log(f'unknown source {SOURCE!r}')
        return
    if os.environ.get('LIVE', 'true').lower() == 'false':
        log('MEETINGS_LIVE is false: nothing to do')
        return
    ctx = None
    try:
        ctx = Ctx(SOURCE)
        log(f'{SOURCE}: {sum(1 for k in ctx.done if k.endswith("/meta.json"))} recordings already on the drive')
        collect(ctx, importlib.import_module(f'meetings.src_{SOURCE}').items(ctx, log))
    except Exception:  # noqa: BLE001
        log('problem:\n' + traceback.format_exc()[-3000:])
    finally:
        if ctx:
            try:
                ctx.save()
            except Exception:  # noqa: BLE001
                log('could not save the state:\n' + traceback.format_exc()[-1500:])
            s = ctx.stats
            log(f'SUMMARY {SOURCE}: collected {s["collected"]}, already on drive {s["already"]}, '
                f'filtered out {s["filtered"]}, blocked {s["blocked"]}, failed {s["failed"]}, '
                f'deferred {s["deferred"]}; files uploaded this run {ctx.state.get("items", 0)} in total so far; '
                f'transcripts {ctx.how}; licences {ctx.licences}')
            if SOURCE.startswith('yt') or ctx.yt_blocked:
                log(f'YouTube: {ctx.yt_ok} downloads worked, {ctx.yt_blocked} refused by the bot check'
                    + (' -> YouTube is BLOCKED for this runner; a cookies secret (YT_COOKIES) would be needed'
                       if ctx.yt_dead else ''))
            summary = os.environ.get('GITHUB_STEP_SUMMARY')
            if summary:
                with open(summary, 'a', encoding='utf-8') as f:
                    f.write(f'### {SOURCE}\n\n{json.dumps(s)}\n\ntranscripts: {json.dumps(ctx.how)}\n\n'
                            f'licences: {json.dumps(ctx.licences)}\n\nYouTube ok/blocked: {ctx.yt_ok}/{ctx.yt_blocked}'
                            f'{" (fully blocked)" if ctx.yt_dead else ""}\n')
    log(f'done in {(time.time() - START) / 60:.0f} min')


if __name__ == '__main__':
    sys.exit(main())
