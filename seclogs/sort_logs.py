"""Sorts the log files of a security-data repository by the tool that recorded them (user, 2026-11-13: endpoint
security, identity and directory, alerts and monitoring logs, real attack simulations only, on shintiru).

  python seclogs/sort_logs.py REPO_DIR RAW_URL_BASE > list.tsv

REPO_DIR is a checkout made without Git LFS downloads (the files are LFS pointers); each line of the output is
"<download address>\t<Drive path>\t<bytes>" for the files from the requested tools. Files from other tools are left
out.
"""
import os
import re
import sys

# (pattern on the file name, then on the folder path) -> Drive folder; the first match wins
TOOLS = [
    (r'crowdstrike|falcon', 'Endpoint Security/CrowdStrike Falcon'),
    (r'sentinel_?one|\bs1_', 'Endpoint Security/SentinelOne'),
    (r'defender|\bmde\b|m365_?d', 'Endpoint Security/Microsoft Defender for Endpoint'),
    (r'linux[-_]?sysmon|sysmon[-_]?linux', 'Endpoint Security/Sysmon for Linux'),
    (r'sysmon', 'Endpoint Security/Sysmon'),
    (r'okta', 'Identity & Directory/Okta System Log'),
    (r'azure[-_]?ad|azuread|entra|signin|aad', 'Identity & Directory/Microsoft Entra ID'),
    (r'bloodhound|sharphound|ldap', 'Identity & Directory/BloodHound, SharpHound & LDAP'),
    (r'windows[-_]?security|security[-_]?xml|xml[-_]?windows[-_]?security|4688|wineventlog[-_:]?security|'
     r'security\.log', 'Identity & Directory/Windows Security Logs (hosts and domain controllers)'),
    (r'notable|splunk[-_]?es', 'Alerts & Monitoring/Splunk Enterprise Security'),
    (r'sentinel', 'Alerts & Monitoring/Microsoft Sentinel'),
]
KEEP_EXT = {'.log', '.json', '.ndjson', '.csv', '.txt', '.xml', '.evtx'}


def tool(path):
    name, folder = os.path.basename(path).lower(), os.path.dirname(path).lower()
    for text in (name, folder):
        for pat, dest in TOOLS:
            if re.search(pat, text):
                return dest
    return None


def main(repo, base):
    for root, _, files in os.walk(os.path.join(repo, 'datasets')):
        for f in files:
            full = os.path.join(root, f)
            rel = os.path.relpath(full, repo).replace(os.sep, '/')
            if os.path.splitext(f)[1].lower() not in KEEP_EXT:
                continue
            dest = tool(rel)
            if not dest:
                continue
            with open(full, 'rb') as fh:
                head = fh.read(200)
            m = re.search(rb'^size (\d+)', head, re.M) if head.startswith(b'version https://git-lfs') else None
            size = int(m.group(1)) if m else os.path.getsize(full)
            sub = rel.split('/', 1)[1]  # drop "datasets/"
            print(f'{base}/{rel}\t{dest}/Splunk Attack Data/{sub}\t{size}')


if __name__ == '__main__':
    main(sys.argv[1], sys.argv[2].rstrip('/'))
