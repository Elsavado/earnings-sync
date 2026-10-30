"""Daily collector check (collector-check.yml): how many files each live collector added to the Workspace drives in
the last 24 hours. A collector that added none is listed in one open issue "Collector check" (the alert); the issue
is closed again once every live collector adds files. The check itself never fails.

User, 2026-10-29: every collector ran and succeeded while adding nothing, and nobody noticed for a day.
"""
import datetime
import json
import os
import subprocess

from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build

TITLE = "Collector check"
# name, LIVE variable, drive variable and default, Drive query for its files, what counts (created or modified)
COLLECTORS = [
    ("Enterprise wide models", "ENTERPRISE_LIVE", "ENTERPRISE_DRIVE_ID", "0AG5EzL2T7ZlfUk9PVA",
     "", "createdTime"),  # the drive holds only its models (tags ent-<kind>)
    ("Sheets, Docs, Slides and bookkeeping", "OFFICE_LIVE", "OFFICE_DRIVE_ID", "0ACsHljU9Hj2_Uk9PVA",
     "appProperties has { key='fdApp' and value='irt-office' }", "createdTime"),
    ("Research notebooks and Figma designs", "RESEARCH_LIVE", "RESEARCH_DRIVE_ID", "0AM6PzKRbJBK-Uk9PVA",
     "appProperties has { key='fdApp' and value='irt-research' }", "createdTime"),
    ("How Companies Work", "HOWCO_LIVE", "HOWCO_DRIVE_ID", "0ACsHljU9Hj2_Uk9PVA",
     "appProperties has { key='hcApp' and value='howco' }", "createdTime"),
    ("Gaming operations data", "GAMING_LIVE", "GAMING_DRIVE_ID", "0APJqW8wSgUmkUk9PVA",
     "", "modifiedTime"),  # mostly updates its own files
    ("Meeting recordings", "MEETINGS_LIVE", "MEETINGS_DRIVE_ID", "0ACsHljU9Hj2_Uk9PVA",
     "appProperties has { key='mtApp' and value='meetings' }", "createdTime"),
]


def drive():
    creds = Credentials(None, refresh_token=os.environ["GOOGLE_REFRESH_TOKEN"], client_id=os.environ["GOOGLE_CLIENT_ID"],
                        client_secret=os.environ["GOOGLE_CLIENT_SECRET"], token_uri="https://oauth2.googleapis.com/token")
    return build("drive", "v3", credentials=creds, cache_discovery=False)


def count(drv, drive_id, tag, field, since):
    """Files added (or changed) since then, up to 1000."""
    q = [f"{field} > '{since}'", "mimeType != 'application/vnd.google-apps.folder'", "trashed = false"]
    if tag:
        q.append(tag)
    res = drv.files().list(q=" and ".join(q), corpora="drive", driveId=drive_id, includeItemsFromAllDrives=True,
                           supportsAllDrives=True, pageSize=1000, fields="files(id)").execute()
    return len(res.get("files", []))


def gh(*args):
    return subprocess.run(["gh", *args], capture_output=True, text=True).stdout.strip()


def main():
    since = (datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(hours=24)).strftime("%Y-%m-%dT%H:%M:%S")
    drv = drive()
    rows, idle = [], []
    for name, live, var, default, tag, field in COLLECTORS:
        if os.environ.get(live, "").lower() != "true":
            rows.append(f"| {name} | off | |")
            continue
        try:
            n = count(drv, os.environ.get(var) or default, tag, field, since)
        except Exception as e:  # a failed count is reported, never a failed run
            rows.append(f"| {name} | ? | could not count: {type(e).__name__} |")
            idle.append(name)
            continue
        what = "changed" if field == "modifiedTime" else "new"
        rows.append(f"| {name} | {'1000+' if n >= 1000 else n} {what} | {'NOTHING ADDED' if n == 0 else 'ok'} |")
        if n == 0:
            idle.append(name)
    table = "| Collector | Files in the last 24 h | |\n|---|---|---|\n" + "\n".join(rows)
    print(table)
    open_issue = json.loads(gh("issue", "list", "--state", "open", "--search", f'"{TITLE}" in:title',
                               "--json", "number,title") or "[]")
    number = next((str(i["number"]) for i in open_issue if i["title"] == TITLE), None)
    if idle:
        body = (f"Checked {since}Z to now. These live collectors added no files: **{', '.join(idle)}**.\n\n{table}\n\n"
                "This issue closes by itself once every live collector adds files again.")
        if number:
            gh("issue", "comment", number, "--body", body)
        else:
            gh("issue", "create", "--title", TITLE, "--body", body)
    elif number:
        gh("issue", "close", number, "--comment", f"Every live collector added files in the last 24 h.\n\n{table}")


if __name__ == "__main__":
    main()
