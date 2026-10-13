"""Downloads numbered Drive folders ('Folder 1 (Models 1-20)', ...) into a local directory so the
workflow can hand them back. Usage:
  python -m models.package <k> <out dir> [--repair]            one folder
  python -m models.package <k>+ <out dir> [--complete]         every folder from k on (complete ones only)
Exit code 3 when there is nothing (complete) to fetch yet."""
import sys
from pathlib import Path

from googleapiclient.http import MediaFileUpload

from . import images, sheets
from .store import FOLDER, MIME, PER_FOLDER, Store, _retry, folder_name
from .xlsxml import Package

MAX_PER_RUN = 150  # folders per batch (3,000 models), keeps the artifact manageable


def _files(store, k):
    name = folder_name((k - 1) * PER_FOLDER + 1)
    q = f"name = '{name}' and mimeType = '{FOLDER}' and '{store.root}' in parents and trashed = false"
    found = _retry(lambda: store.drive.files().list(q=q, fields='files(id)').execute())['files']
    if not found:
        return name, None
    files = _retry(lambda: store.drive.files().list(q=f"'{found[0]['id']}' in parents and trashed = false",
                                                    fields='files(id, name)', pageSize=100).execute())['files']
    return name, files


def fetch(store, k, out, repair=False):
    name, files = _files(store, k)
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


def main(arg, out):
    store = Store()
    repair, complete = '--repair' in sys.argv, '--complete' in sys.argv
    if arg.endswith('+'):
        k, got = int(arg[:-1]), 0
        while got < MAX_PER_RUN:
            name, files = _files(store, k)
            if files is None or len(files) < PER_FOLDER:
                break
            fetch(store, k, out, repair)
            k, got = k + 1, got + 1
        print(f'fetched {got} complete folder(s); next folder {k}')
        if not got:
            raise SystemExit(3)
        return
    k = int(arg)
    name, files = _files(store, k)
    if files is None or (complete and len(files) < PER_FOLDER):
        print(f'{name}: not complete yet')
        raise SystemExit(3)
    fetch(store, k, out, repair)


if __name__ == '__main__':
    main(sys.argv[1], sys.argv[2])
