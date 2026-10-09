import { createReadStream } from 'node:fs';
import { Readable } from 'node:stream';
import { google } from 'googleapis';

const FOLDER_MIME = 'application/vnd.google-apps.folder';
const SHEET_MIME = 'application/vnd.google-apps.spreadsheet';
export const APP_KEY = 'mdApp';
export const APP_VALUE = 'medical-sync';
const SOURCE_KEY = 'mdSourceKey';
const CATEGORY_KEY = 'mdCategory';
const SUBTYPE_KEY = 'mdSubtype';

function escapeQuery(value) {
  return String(value).replace(/\\/g, '\\\\').replace(/'/g, "\\'");
}

export function hasDriveCredentials() {
  return Boolean(
    process.env.GOOGLE_SERVICE_ACCOUNT_JSON ||
      (process.env.GOOGLE_CLIENT_ID && process.env.GOOGLE_CLIENT_SECRET && process.env.GOOGLE_REFRESH_TOKEN)
  );
}

function buildAuth() {
  if (process.env.GOOGLE_SERVICE_ACCOUNT_JSON) {
    let credentials;
    try {
      credentials = JSON.parse(process.env.GOOGLE_SERVICE_ACCOUNT_JSON);
    } catch {
      throw new Error('GOOGLE_SERVICE_ACCOUNT_JSON is not valid JSON; paste the whole key file contents into the secret');
    }
    return {
      kind: 'service-account',
      auth: new google.auth.GoogleAuth({ credentials, scopes: ['https://www.googleapis.com/auth/drive'] })
    };
  }
  const { GOOGLE_CLIENT_ID, GOOGLE_CLIENT_SECRET, GOOGLE_REFRESH_TOKEN } = process.env;
  if (GOOGLE_CLIENT_ID && GOOGLE_CLIENT_SECRET && GOOGLE_REFRESH_TOKEN) {
    const oauth = new google.auth.OAuth2(GOOGLE_CLIENT_ID, GOOGLE_CLIENT_SECRET);
    oauth.setCredentials({ refresh_token: GOOGLE_REFRESH_TOKEN });
    return { kind: 'oauth', auth: oauth };
  }
  throw new Error(
    'No Google Drive credentials. Set GOOGLE_CLIENT_ID, GOOGLE_CLIENT_SECRET and GOOGLE_REFRESH_TOKEN, or GOOGLE_SERVICE_ACCOUNT_JSON with DRIVE_ROOT_FOLDER_ID'
  );
}

export class DriveStore {
  constructor(drive, { kind, rootFolderId, rootFolderName }) {
    this.drive = drive;
    this.kind = kind;
    this.rootFolderId = rootFolderId || null;
    this.rootFolderName = rootFolderName;
    this.folderCache = new Map();
  }

  async init() {
    if (this.rootFolderId) {
      const res = await this.drive.files.get({ fileId: this.rootFolderId, fields: 'id, mimeType', supportsAllDrives: true });
      if (res.data.mimeType !== FOLDER_MIME) throw new Error(`DRIVE_ROOT_FOLDER_ID ${this.rootFolderId} is not a folder`);
      return this;
    }
    if (this.kind === 'service-account') {
      throw new Error(
        'Service accounts have no storage of their own. Set DRIVE_ROOT_FOLDER_ID to a folder inside a Shared Drive the service account can edit, or use the OAuth credentials instead'
      );
    }
    this.rootFolderId = await this.ensureFolder('root', this.rootFolderName);
    return this;
  }

  async ensureFolder(parentId, name) {
    const cacheKey = `${parentId}/${name}`;
    if (this.folderCache.has(cacheKey)) return this.folderCache.get(cacheKey);
    const q = [`name = '${escapeQuery(name)}'`, `mimeType = '${FOLDER_MIME}'`, `'${escapeQuery(parentId)}' in parents`, 'trashed = false'].join(' and ');
    const found = await this.drive.files.list({
      q,
      fields: 'files(id)',
      pageSize: 10,
      supportsAllDrives: true,
      includeItemsFromAllDrives: true,
      corpora: 'allDrives'
    });
    let id = found.data.files?.[0]?.id;
    if (!id) {
      const created = await this.drive.files.create({
        requestBody: { name, mimeType: FOLDER_MIME, parents: [parentId] },
        fields: 'id',
        supportsAllDrives: true
      });
      id = created.data.id;
    }
    this.folderCache.set(cacheKey, id);
    return id;
  }

  // Folder path under the root, e.g. ['Pathology', 'Whole-slide images', 'Breast'].
  async ensurePath(parts) {
    let id = this.rootFolderId;
    for (const part of parts) id = await this.ensureFolder(id, String(part).slice(0, 120) || 'Unsorted');
    return id;
  }

  async listAppFiles() {
    const files = [];
    let pageToken;
    do {
      const res = await this.drive.files.list({
        q: `appProperties has { key='${APP_KEY}' and value='${APP_VALUE}' } and trashed = false`,
        fields: 'nextPageToken, files(id, name, size, mimeType, parents, appProperties)',
        pageSize: 1000,
        pageToken,
        supportsAllDrives: true,
        includeItemsFromAllDrives: true,
        corpora: 'allDrives'
      });
      files.push(...(res.data.files || []));
      pageToken = res.data.nextPageToken;
    } while (pageToken);
    return files;
  }

  async loadExistingSourceKeys() {
    const keys = new Set();
    for (const file of await this.listAppFiles()) {
      const key = file.appProperties?.[SOURCE_KEY];
      if (key) keys.add(key);
    }
    return keys;
  }

  // Marks an unpacked archive's folder as finished by tagging the folder itself, so no
  // bookkeeping file has to sit next to the data.
  async markFolderDone(folderId, sourceKey) {
    await this.drive.files.update({
      fileId: folderId,
      requestBody: { appProperties: { [APP_KEY]: APP_VALUE, [SOURCE_KEY]: sourceKey } },
      supportsAllDrives: true
    });
  }

  async trash(fileId) {
    await this.drive.files.update({ fileId, requestBody: { trashed: true }, supportsAllDrives: true });
  }

  async readSheetCsv(folderId, name) {
    const file = await this.findFile(folderId, name);
    if (!file) return null;
    const res = await this.drive.files.export({ fileId: file.id, mimeType: 'text/csv' }, { responseType: 'text' });
    return String(res.data);
  }

  // Bytes still free before the reserve is reached; null when the account has no limit.
  async freeBytes(reserveBytes) {
    const res = await this.drive.about.get({ fields: 'storageQuota(limit, usage)' });
    const { limit, usage } = res.data.storageQuota || {};
    if (!limit) return null;
    return Number(limit) - Number(usage) - reserveBytes;
  }

  async findFile(folderId, name) {
    const res = await this.drive.files.list({
      q: `name = '${escapeQuery(name)}' and '${escapeQuery(folderId)}' in parents and trashed = false`,
      fields: 'files(id)',
      pageSize: 1,
      supportsAllDrives: true,
      includeItemsFromAllDrives: true,
      corpora: 'allDrives'
    });
    return res.data.files?.[0] || null;
  }

  // Writes CSV into a Google Sheet (no Drive storage used), replacing its content in place.
  async writeSheet(folderId, name, csv) {
    const media = { mimeType: 'text/csv', body: Readable.from(Buffer.from(csv, 'utf8')) };
    const existing = await this.findFile(folderId, name);
    if (existing) {
      return (await this.drive.files.update({ fileId: existing.id, media, fields: 'id, webViewLink', supportsAllDrives: true })).data;
    }
    return (
      await this.drive.files.create({
        requestBody: { name, parents: [folderId], mimeType: SHEET_MIME },
        media,
        fields: 'id, webViewLink',
        supportsAllDrives: true
      })
    ).data;
  }

  // One of `filePath` (streamed from disk), `buffer`, or a readable `stream` (a zip entry).
  async upload({ folderId, name, filePath, buffer, stream, mimeType, sourceKey, category, subtype, description }) {
    const body = filePath ? createReadStream(filePath) : stream || Readable.from(buffer);
    const res = await this.drive.files.create({
      requestBody: {
        name,
        parents: [folderId],
        description,
        // Drive limits a property's key plus value to 124 bytes, so the sub-type is shortened.
        appProperties: { [APP_KEY]: APP_VALUE, [SOURCE_KEY]: sourceKey, [CATEGORY_KEY]: category, [SUBTYPE_KEY]: String(subtype || '').slice(0, 100) }
      },
      media: { mimeType, body },
      fields: 'id, name, webViewLink',
      supportsAllDrives: true
    });
    return res.data;
  }
}

export async function createDriveStore(settings) {
  const { kind, auth } = buildAuth();
  const drive = google.drive({ version: 'v3', auth });
  const store = new DriveStore(drive, {
    kind,
    rootFolderId: process.env.DRIVE_ROOT_FOLDER_ID || null,
    rootFolderName: settings.driveRootFolderName
  });
  return store.init();
}
