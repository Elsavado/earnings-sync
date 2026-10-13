"""Downloads one numbered Drive folder ('Folder 1 (Models 1-20)') into a local directory, so the
workflow can hand it back as a zip. Usage: python -m models.package <folder number> <out dir>"""
import sys
from pathlib import Path

from googleapiclient.http import MediaFileUpload

from . import images, sheets
from .store import FOLDER, MIME, Store, _retry, folder_name
from .xlsxml import Package


def main(k, out, repair=False):
    store = Store()
    name = folder_name((k - 1) * 20 + 1)
    q = f"name = '{name}' and mimeType = '{FOLDER}' and '{store.root}' in parents and trashed = false"
    found = _retry(lambda: store.drive.files().list(q=q, fields='files(id)').execute())['files']
    if not found:
        raise SystemExit(f'{name} not found in Drive')
    files = _retry(lambda: store.drive.files().list(q=f"'{found[0]['id']}' in parents and trashed = false",
                                                    fields='files(id, name)', pageSize=100).execute())['files']
    dest = Path(out) / name
    dest.mkdir(parents=True, exist_ok=True)
    for f in files:
        data = _retry(lambda: store.drive.files().get_media(fileId=f['id']).execute())
        path = dest / f['name']
        path.write_bytes(data)
        if repair:
            pkg = Package(path)
            images.strip(pkg)
            dropped = sheets.drop_empty(pkg)
            if dropped and not pkg.broken_parts():
                pkg.save(path)
                ext = path.suffix.lstrip('.')
                _retry(lambda: store.drive.files().update(fileId=f['id'], media_body=MediaFileUpload(str(path), mimetype=MIME[ext])).execute())
                print(f'  repaired {f["name"]}: removed empty tab(s) {dropped}')
    print(f'{name}: {len(files)} file(s)')


if __name__ == '__main__':
    main(int(sys.argv[1]), sys.argv[2], repair='--repair' in sys.argv)
