"""Audio download and conversion, transcript formats (VTT / SRT parsing, VTT + timestamped text output), yt-dlp
with YouTube bot-check detection, and faster-whisper speech recognition on the runner's CPU."""
import hashlib
import html
import os
import re
import subprocess
import time
from pathlib import Path

import requests

UA = 'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36'
BLOCK = re.compile(r'confirm you.{0,3}re not a bot|Sign in to confirm|HTTP Error 429|Too Many Requests|'
                   r'This content isn.t available|LOGIN_REQUIRED|po_token', re.I)


class Skip(Exception):
    """The item is not wanted (topic, language, licence); not a failure."""


class OutOfTime(Exception):
    """Not enough run time left for this item (it is tried again on a later run)."""


class Blocked(Exception):
    """YouTube refused the runner (bot check / rate limit)."""


def rec_id(source, item_id):
    return hashlib.sha1(f'{source}:{item_id}'.encode()).hexdigest()[:16]


def have(ctx, item_id):
    """True when the recording is complete on the drive (its meta.json is there)."""
    return f'{rec_id(ctx.source, item_id)}/meta.json' in ctx.done


def session():
    s = requests.Session()
    s.headers['User-Agent'] = UA
    return s


def fetch(s, url, dest, timeout=120):
    """Streams url to dest; returns the size."""
    with s.get(url, stream=True, timeout=timeout) as r:
        r.raise_for_status()
        with open(dest, 'wb') as f:
            for chunk in r.iter_content(4 * 2**20):
                f.write(chunk)
    return os.path.getsize(dest)


def to_audio(src, dest, timeout=3 * 3600):
    """Any audio/video file or stream (src may be an URL) -> mono 64 kbps AAC (.m4a). Returns the duration (s)."""
    cmd = ['ffmpeg', '-nostdin', '-loglevel', 'error', '-y', '-i', str(src), '-vn', '-ac', '1', '-ar', '22050',
           '-c:a', 'aac', '-b:a', '64k', '-movflags', '+faststart', str(dest)]
    subprocess.run(cmd, check=True, timeout=timeout, capture_output=True)
    return duration(dest)


def duration(path):
    out = subprocess.run(['ffprobe', '-v', 'error', '-show_entries', 'format=duration', '-of', 'csv=p=0', str(path)],
                         capture_output=True, text=True, timeout=120).stdout.strip()
    try:
        return float(out)
    except ValueError:
        return 0.0


# --- transcripts --------------------------------------------------------------------------------------------
def _ts(t):
    t = max(0.0, float(t))
    h, rem = divmod(t, 3600)
    m, s = divmod(rem, 60)
    return f'{int(h):02d}:{int(m):02d}:{s:06.3f}'


def _secs(stamp):
    parts = stamp.replace(',', '.').split(':')
    parts = [float(p) for p in parts]
    while len(parts) < 3:
        parts.insert(0, 0.0)
    return parts[0] * 3600 + parts[1] * 60 + parts[2]


CUE = re.compile(r'((?:\d+:)?\d{1,2}:\d{2}[.,]\d{3})\s*-->\s*((?:\d+:)?\d{1,2}:\d{2}[.,]\d{3})[^\n]*\n(.*?)(?=\n\s*\n|\Z)',
                 re.S)


def parse_captions(text):
    """VTT or SRT text -> segments [{'start','end','text','speaker'}]. Rolling auto-caption lines (each line shown in
    two cues) are kept once."""
    text = text.replace('\r\n', '\n').replace('\r', '\n')
    segs, last = [], ''
    for m in CUE.finditer(text):
        lines = []
        for line in m.group(3).split('\n'):
            line = html.unescape(re.sub(r'<[^>]+>', '', line)).strip()
            if line and line != last and line not in lines:
                lines.append(line)
        lines = [x for x in lines if x != last]
        if not lines:
            continue
        last = lines[-1]
        segs.append({'start': _secs(m.group(1)), 'end': _secs(m.group(2)), 'text': ' '.join(lines), 'speaker': None})
    return segs


def write_transcript(segs, folder):
    """Writes transcript.vtt and transcript.txt ([hh:mm:ss] Speaker: text). Returns the file names."""
    vtt, txt = ['WEBVTT', ''], []
    for i, s in enumerate(segs, 1):
        who = f"{s['speaker']}: " if s.get('speaker') else ''
        vtt += [str(i), f"{_ts(s['start'])} --> {_ts(max(s['end'], s['start'] + 0.1))}", who + s['text'], '']
        txt.append(f"[{_ts(s['start'])[:8]}] {who}{s['text']}")
    Path(folder, 'transcript.vtt').write_text('\n'.join(vtt), encoding='utf-8')
    Path(folder, 'transcript.txt').write_text('\n'.join(txt) + '\n', encoding='utf-8')
    return ['transcript.vtt', 'transcript.txt']


def words_to_segments(words, gap=1.0, max_len=30.0):
    """[(start, end, word, speaker)] sorted by time -> segments, split at speaker changes, pauses and length."""
    segs = []
    for st, en, w, spk in words:
        cur = segs[-1] if segs else None
        if (cur and cur['speaker'] == spk and st - cur['end'] <= gap and en - cur['start'] <= max_len):
            cur['text'] += w if re.match(r'^[.,?!;:]', w) else ' ' + w
            cur['end'] = max(cur['end'], en)
        else:
            segs.append({'start': st, 'end': en, 'text': w, 'speaker': spk})
    return segs


# --- speech recognition -------------------------------------------------------------------------------------
class ASR:
    """faster-whisper on CPU (int8). Tracks its speed (seconds of audio per second of work)."""

    def __init__(self, log):
        self.log, self.model, self.speed, self.name = log, None, 12.0, os.environ.get('ASR_MODEL', 'base.en')

    def estimate(self, secs):
        return secs / self.speed + 60

    def run(self, audio, secs):
        from faster_whisper import WhisperModel
        if self.model is None:
            self.model = WhisperModel(self.name, device='cpu', compute_type='int8', cpu_threads=os.cpu_count() or 4)
        t0 = time.time()
        # decoded by ffmpeg (16 kHz mono float32), so PyAV's file reader is never needed
        import numpy as np
        pcm = subprocess.run(['ffmpeg', '-nostdin', '-loglevel', 'error', '-i', str(audio), '-f', 's16le', '-ac', '1',
                              '-ar', '16000', '-'], capture_output=True, check=True, timeout=3600).stdout
        wave = np.frombuffer(pcm, np.int16).astype(np.float32) / 32768.0
        del pcm
        parts, _ = self.model.transcribe(wave, language='en', beam_size=1, vad_filter=True,
                                         condition_on_previous_text=False)
        segs = [{'start': p.start, 'end': p.end, 'text': p.text.strip(), 'speaker': None} for p in parts if p.text.strip()]
        took = max(1.0, time.time() - t0)
        if secs > 120:
            self.speed = 0.5 * self.speed + 0.5 * (secs / took)
        self.log(f'  ASR {self.name}: {secs / 60:.0f} min of audio in {took / 60:.1f} min ({secs / took:.1f}x)')
        return segs


# --- yt-dlp -------------------------------------------------------------------------------------------------
def ytdlp_opts(extra=None):
    o = {'quiet': True, 'no_warnings': True, 'noprogress': True, 'socket_timeout': 30, 'retries': 3,
         'extractor_retries': 2, 'noplaylist': True, 'ignoreerrors': False}
    cookies = os.environ.get('YT_COOKIES_FILE')
    if cookies and os.path.exists(cookies) and os.path.getsize(cookies) > 0:
        o['cookiefile'] = cookies
    o.update(extra or {})
    return o


def listing(url, limit=200):
    """Flat entries of a channel / playlist / search: [{'id','url','title','duration','channel'}]."""
    from yt_dlp import YoutubeDL
    with YoutubeDL(ytdlp_opts({'extract_flat': 'in_playlist', 'playlistend': limit, 'noplaylist': False})) as ydl:
        info = ydl.extract_info(url, download=False)
    out = []
    for e in (info or {}).get('entries') or []:
        if not e:
            continue
        if e.get('entries'):  # a channel tab inside a channel
            out += [x for x in e['entries'] if x]
        else:
            out.append(e)
    return out[:limit]


def _pick_sub(tracks):
    """English track list -> (url, ext) of a vtt (or srt) entry."""
    for lang in ('en-orig', 'en', 'en-US', 'en-CA', 'en-GB'):
        if lang not in (tracks or {}):
            continue
        for want in ('vtt', 'srt'):
            for t in tracks[lang]:
                if t.get('ext') == want and t.get('url'):
                    return t['url'], want
    return None


def ytdlp_get(url, work, info_check=None):
    """Downloads the best audio of url into work and the best English captions. Returns (info, media file,
    segments or None, 'captions'|'auto-captions'|None). info_check(info) may raise Skip to skip the item
    before anything is downloaded. Raises Blocked on a bot check."""
    from yt_dlp import YoutubeDL
    from yt_dlp.utils import DownloadError, ExtractorError
    opts = ytdlp_opts({'format': 'bestaudio[abr<=160]/bestaudio/best[height<=360]/best',
                       'outtmpl': str(Path(work, 'src.%(ext)s'))})
    try:
        with YoutubeDL(opts) as ydl:
            info = ydl.extract_info(url, download=False)
            if info_check:
                info_check(info)
            segs, how = None, None
            for tracks, kind in ((info.get('subtitles'), 'captions'), (info.get('automatic_captions'), 'auto-captions')):
                pick = _pick_sub(tracks)
                if pick:
                    try:
                        raw = ydl.urlopen(pick[0]).read().decode('utf-8', 'replace')
                        segs = parse_captions(raw)
                    except Exception:  # noqa: BLE001 - captions are optional (ASR follows)
                        segs = None
                    if segs:
                        how = kind
                        break
            info = ydl.process_ie_result(info, download=True)
    except (DownloadError, ExtractorError) as err:
        if BLOCK.search(str(err)):
            raise Blocked(str(err)[:300]) from err
        raise
    files = [p for p in Path(work).glob('src.*') if not p.name.endswith(('.part', '.ytdl'))]
    if not files:
        raise RuntimeError('yt-dlp produced no file')
    return info, files[0], segs, how
