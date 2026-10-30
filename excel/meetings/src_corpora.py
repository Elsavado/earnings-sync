"""Open meeting corpora (allowed outside the finance topic rule: the user chose them).

  Open Meeting Corpora/Earnings-21 (earnings calls)/<company> earnings call .../   CC BY-SA 4.0 (Rev.com)
  Open Meeting Corpora/AMI Meeting Corpus/<date> AMI meeting ES2002a .../          CC BY 4.0 (Edinburgh)
  Open Meeting Corpora/ICSI Meeting Corpus/<date> ICSI meeting Bmr001/             CC BY 4.0 (Edinburgh / ICSI)

Transcripts are the corpora's own manual transcripts with their timings (AMI: word-level times; ICSI: segment
times; Earnings-21: the reference transcript laid over the dataset's speaker-turn timings).
"""
import csv
import html
import io
import re
import xml.etree.ElementTree as ET
import zipfile

from . import media

AMI_ZIP = 'https://groups.inf.ed.ac.uk/ami/AMICorpusAnnotations/ami_public_manual_1.6.2.zip'
AMI_WAV = 'https://groups.inf.ed.ac.uk/ami/AMICorpusMirror/amicorpus/{m}/audio/{m}.Mix-Headset.wav'
ICSI_ZIP = 'https://groups.inf.ed.ac.uk/ami/ICSICorpusAnnotations/ICSI_original_transcripts.zip'
ICSI_WAV = 'https://groups.inf.ed.ac.uk/ami/ICSIsignals/NXT/{m}.interaction.wav'
E21 = 'https://raw.githubusercontent.com/revdotcom/speech-datasets/main/earnings21/'
CC_BY = 'https://creativecommons.org/licenses/by/4.0/'
ROLES = {'PM': 'Project Manager', 'ME': 'Marketing Expert', 'UI': 'User Interface Designer',
         'ID': 'Industrial Designer'}


def _zip(ctx, url):
    r = ctx.http.get(url, timeout=300)
    r.raise_for_status()
    return zipfile.ZipFile(io.BytesIO(r.content))


# --- Earnings-21 ------------------------------------------------------------------------------------------
def _e21_segments(ctx, fid):
    nlp = ctx.http.get(f'{E21}transcripts/nlp_references/{fid}.nlp', timeout=120).text.splitlines()
    rttm = ctx.http.get(f'{E21}rttms/{fid}.rttm', timeout=120).text.splitlines()
    turns = []  # (speaker, [words])
    for row in nlp[1:]:
        p = row.split('|')
        if len(p) < 5 or not p[0]:
            continue
        w = p[0] + (p[4] or '')
        if turns and turns[-1][0] == p[1]:
            turns[-1][1].append(w)
        else:
            turns.append((p[1], [w]))
    spans = []  # (speaker, [(start, end)])
    for row in rttm:
        p = row.split()
        if len(p) < 8 or p[0] != 'SPEAKER':
            continue
        st, du, spk = float(p[3]), float(p[4]), p[7]
        if spans and spans[-1][0] == spk:
            spans[-1][1].append((st, st + du))
        else:
            spans.append((spk, [(st, st + du)]))
    if len(turns) != len(spans) or any(a[0] != b[0] for a, b in zip(turns, spans)):
        return None  # timings do not line up: speech recognition instead
    segs = []
    for (spk, words), (_, parts) in zip(turns, spans):
        total = sum(e - s for s, e in parts) or 1.0
        i = 0
        for k, (s, e) in enumerate(parts):
            n = len(words) - i if k == len(parts) - 1 else round(len(words) * (e - s) / total)
            chunk = words[i:i + n]
            i += n
            if chunk:
                segs.append({'start': s, 'end': e, 'text': ' '.join(chunk), 'speaker': f'Speaker {int(spk) + 1}'})
    return segs


def earnings21(ctx, log):
    rows = list(csv.DictReader(io.StringIO(ctx.http.get(f'{E21}earnings21-file-metadata.csv', timeout=120).text)))
    log(f'Earnings-21: {len(rows)} calls')
    for r in rows:
        fid = r['file_id']
        yield {'id': f'e21:{fid}', 'type': 'corpora', 'group': 'Earnings-21 (earnings calls)',
               'org': r['company_name'], 'title': f"{r['company_name']} earnings call (fiscal Q{r['financial_quarter']}) "
                                                 f"[{fid}]",
               'url': 'https://github.com/revdotcom/speech-datasets/tree/main/earnings21', 'date': '',
               'licence': 'CC BY-SA 4.0 (Earnings-21 transcripts; audio as distributed with the dataset)',
               'licence_url': 'https://creativecommons.org/licenses/by-sa/4.0/',
               'media': [('direct', f'{E21}media/{fid}.mp3')],
               'segments': lambda fid=fid: _e21_segments(ctx, fid),
               'segments_how': 'Earnings-21 reference transcript (Rev.com), timed by the dataset\'s speaker turns (RTTM)',
               'meta': {'corpus': 'Earnings-21 (Rev.com, 2021)', 'sector': r.get('sector'),
                        'speakers': r.get('unique_speakers'), 'corpus_file_id': fid}}


# --- AMI -------------------------------------------------------------------------------------------------
def _ami_segments(z, m, speakers):
    words = []
    for name in z.namelist():
        mm = re.match(rf'words/{re.escape(m)}\.([A-Z])\.words\.xml$', name)
        if not mm:
            continue
        agent = mm.group(1)
        who = speakers.get(agent) or f'Speaker {agent}'
        last = 0.0
        for el in ET.fromstring(z.read(name)):
            if el.tag != 'w' or not (el.text or '').strip():
                continue
            st = float(el.get('starttime') or last)
            en = float(el.get('endtime') or st)
            last = en
            words.append((st, en, html.unescape(el.text.strip()), who))
    words.sort(key=lambda w: w[0])
    return media.words_to_segments(words) or None


def ami(ctx, log):
    z = _zip(ctx, AMI_ZIP)
    meets = {}
    root = ET.fromstring(z.read('corpusResources/meetings.xml'))
    for el in root:
        obs = el.get('observation')
        spk = {}
        for s in el:
            role = ROLES.get(s.get('role') or '')
            spk[s.get('nxt_agent')] = f"{role} ({s.get('nxt_agent')})" if role else f"Speaker {s.get('nxt_agent')}"
        d = el.get('dateOnly') or ''
        dm = re.match(r'(\d{1,2})-(\d{1,2})-(\d{4})', d)
        meets[obs] = {'type': el.get('type') or '', 'date': f'{dm.group(3)}-{int(dm.group(2)):02d}-{int(dm.group(1)):02d}'
                      if dm else '', 'speakers': spk}
    have = sorted({n.split('/')[1].split('.')[0] for n in z.namelist() if n.startswith('words/') and n.endswith('.xml')})
    log(f'AMI: {len(have)} meetings with manual transcripts')
    for m in have:
        info = meets.get(m, {'type': '', 'date': '', 'speakers': {}})
        kind = 'scenario (design-team role play)' if info['type'] == 'scenario' else 'non-scenario (real meeting)'
        yield {'id': f'ami:{m}', 'type': 'corpora', 'group': 'AMI Meeting Corpus', 'org': 'AMI Consortium',
               'title': f'AMI meeting {m} - {kind}', 'date': info['date'],
               'url': 'https://groups.inf.ed.ac.uk/ami/corpus/', 'licence': 'CC BY 4.0', 'licence_url': CC_BY,
               'media': [('direct', AMI_WAV.format(m=m))],
               'segments': lambda m=m, s=info['speakers']: _ami_segments(z, m, s),
               'segments_how': 'AMI manual transcript (v1.6.2), word-level timings',
               'meta': {'corpus': 'AMI Meeting Corpus', 'meeting_id': m, 'meeting_kind': kind,
                        'audio_source': 'Mix-Headset'}}


# --- ICSI ------------------------------------------------------------------------------------------------
def _icsi_text(seg):
    t = ' '.join(x.strip() for x in seg.itertext() if x.strip())
    t = re.sub(r'\b((?:[A-Za-z]_)+[A-Za-z])\b', lambda m: m.group(1).replace('_', ''), t)
    return re.sub(r'\s+', ' ', t).strip()


def _icsi(z, name):
    root = ET.fromstring(z.read(name))
    segs = []
    for seg in root.iter('Segment'):
        text = _icsi_text(seg)
        if not text:
            continue
        st, en = float(seg.get('StartTime') or 0), float(seg.get('EndTime') or 0)
        who = seg.get('Participant') or 'Speaker'
        cur = segs[-1] if segs else None
        if cur and cur['speaker'] == who and st - cur['end'] < 1.0 and en - cur['start'] < 30:
            cur['text'] += ' ' + text
            cur['end'] = max(cur['end'], en)
        else:
            segs.append({'start': st, 'end': en, 'text': text, 'speaker': who})
    segs.sort(key=lambda s: s['start'])
    return root, segs


def icsi(ctx, log):
    z = _zip(ctx, ICSI_ZIP)
    names = sorted(n for n in z.namelist() if n.startswith('transcripts/') and n.endswith('.mrt'))
    log(f'ICSI: {len(names)} meetings')
    for n in names:
        m = n.split('/')[-1][:-4]
        try:
            root = ET.fromstring(z.read(n))
        except ET.ParseError:
            continue
        dt = re.match(r'(\d{4})-(\d{2})-(\d{2})', root.get('DateTimeStamp') or '')
        yield {'id': f'icsi:{m}', 'type': 'corpora', 'group': 'ICSI Meeting Corpus',
               'org': 'International Computer Science Institute', 'title': f'ICSI meeting {m}',
               'date': '-'.join(dt.groups()) if dt else '', 'url': 'https://groups.inf.ed.ac.uk/ami/icsi/',
               'licence': 'CC BY 4.0', 'licence_url': CC_BY, 'media': [('direct', ICSI_WAV.format(m=m))],
               'segments': lambda n=n: _icsi(z, n)[1] or None,
               'segments_how': 'ICSI original manual transcript (segment timings; participants by corpus code)',
               'meta': {'corpus': 'ICSI Meeting Corpus', 'meeting_id': m, 'audio_source': 'interaction (mixed) wav'}}


def items(ctx, log):
    for gen in (earnings21, ami, icsi):
        try:
            yield from gen(ctx, log)
        except Exception as e:  # noqa: BLE001 - one corpus failing never stops the others
            log(f'{gen.__name__}: could not list ({type(e).__name__}: {str(e)[:200]})')
