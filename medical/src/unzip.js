// Walks a zip file entry by entry, handing each file's stream to `onEntry`, so archives
// are unpacked straight to Drive without writing their contents to disk.
import yauzl from 'yauzl';

export function forEachZipEntry(zipPath, onEntry) {
  return new Promise((resolve, reject) => {
    yauzl.open(zipPath, { lazyEntries: true, autoClose: true }, (err, zip) => {
      if (err) return reject(err);
      let count = 0;
      zip.on('error', reject);
      zip.on('end', () => resolve(count));
      zip.on('entry', (entry) => {
        // Directories, macOS metadata and absolute or parent-relative paths are skipped.
        const name = entry.fileName;
        if (name.endsWith('/') || /(^|\/)__MACOSX\//.test(name) || /(^|\/)\.DS_Store$/.test(name) || name.startsWith('/') || name.split('/').includes('..')) {
          zip.readEntry();
          return;
        }
        Promise.resolve(onEntry(entry, () => new Promise((res, rej) => zip.openReadStream(entry, (e, s) => (e ? rej(e) : res(s))))))
          .then((handled) => {
            if (handled === false) {
              zip.close();
              resolve(count);
              return;
            }
            count++;
            zip.readEntry();
          })
          .catch((e) => {
            zip.close();
            reject(e);
          });
      });
      zip.readEntry();
    });
  });
}

// Reads only the central directory: the names of the files in the archive.
export async function listZipFiles(zipPath) {
  const names = [];
  await forEachZipEntry(zipPath, (entry) => {
    names.push(entry.fileName);
  });
  return names;
}

// Many archives wrap everything in one top-level folder; drop it so the item folder is not
// nested twice.
export function stripCommonRoot(paths) {
  if (paths.length === 0) return '';
  const first = paths[0].split('/');
  if (first.length < 2) return '';
  const root = `${first[0]}/`;
  return paths.every((p) => p.startsWith(root)) ? root : '';
}
