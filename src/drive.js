import { Readable } from 'node:stream';
import { google } from 'googleapis';

const FOLDER_MIME = 'application/vnd.google-apps.folder';
const GOOGLE_DOC_MIME = 'application/vnd.google-apps.document';
const APP_KEY = 'irApp';
const APP_VALUE = 'earnings-sync';
const SOURCE_KEY = 'irSourceKey';

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
      const res = await this.drive.files.get({
        fileId: this.rootFolderId,
        fields: 'id, name, mimeType',
        supportsAllDrives: true
      });
      if (res.data.mimeType !== FOLDER_MIME) {
        throw new Error(`DRIVE_ROOT_FOLDER_ID ${this.rootFolderId} is not a folder`);
      }
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
    const q = [
      `name = '${escapeQuery(name)}'`,
      `mimeType = '${FOLDER_MIME}'`,
      `'${escapeQuery(parentId)}' in parents`,
      'trashed = false'
    ].join(' and ');
    const found = await this.drive.files.list({
      q,
      fields: 'files(id, name)',
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

  async loadExistingSourceKeys() {
    const keys = new Set();
    let pageToken;
    do {
      const res = await this.drive.files.list({
        q: `appProperties has { key='${APP_KEY}' and value='${APP_VALUE}' } and trashed = false`,
        fields: 'nextPageToken, files(id, appProperties)',
        pageSize: 1000,
        pageToken,
        supportsAllDrives: true,
        includeItemsFromAllDrives: true,
        corpora: 'allDrives'
      });
      for (const file of res.data.files || []) {
        const key = file.appProperties?.[SOURCE_KEY];
        if (key) keys.add(key);
      }
      pageToken = res.data.nextPageToken;
    } while (pageToken);
    return keys;
  }

  // Bytes still free before the reserve is reached; null when the account has no limit.
  async freeBytes(reserveBytes) {
    const res = await this.drive.about.get({ fields: 'storageQuota(limit, usage)' });
    const { limit, usage } = res.data.storageQuota || {};
    if (!limit) return null;
    return Number(limit) - Number(usage) - reserveBytes;
  }

  async findPrivateFile(folderId, name) {
    const res = await this.drive.files.list({
      q: `name = '${escapeQuery(name)}' and '${escapeQuery(folderId)}' in parents and trashed = false`,
      fields: 'files(id, appProperties)',
      pageSize: 1,
      supportsAllDrives: true,
      includeItemsFromAllDrives: true,
      corpora: 'allDrives'
    });
    return res.data.files?.[0] || null;
  }

  // The code -> company key, stored as a Google Sheet (no Drive storage used). Replaced
  // only when its content changes. Returns false when unchanged.
  async writeKeySheet(folderId, name, csv, contentHash) {
    const existing = await this.findPrivateFile(folderId, name);
    if (existing && existing.appProperties?.irHash === contentHash) return false;
    await this.drive.files.create({
      requestBody: { name, parents: [folderId], mimeType: 'application/vnd.google-apps.spreadsheet', appProperties: { irPrivate: '1', irHash: contentHash } },
      media: { mimeType: 'text/csv', body: Readable.from(Buffer.from(csv, 'utf8')) },
      fields: 'id',
      supportsAllDrives: true
    });
    if (existing) await this.drive.files.delete({ fileId: existing.id, supportsAllDrives: true });
    return true;
  }

  // Every file this app created, for the one-off cleanup.
  async listAppFiles() {
    const files = [];
    let pageToken;
    do {
      const res = await this.drive.files.list({
        q: 'trashed = false',
        fields: 'nextPageToken, files(id, name, mimeType, size, parents, appProperties)',
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

  async deleteFile(fileId) {
    await this.drive.files.delete({ fileId, supportsAllDrives: true });
  }

  async upload({ folderId, name, buffer, mimeType, sourceKey, convertToGoogleDoc }) {
    const requestBody = {
      name,
      parents: [folderId],
      description: 'Collected and anonymised by earnings-sync',
      appProperties: { [APP_KEY]: APP_VALUE, [SOURCE_KEY]: sourceKey }
    };
    if (convertToGoogleDoc) requestBody.mimeType = GOOGLE_DOC_MIME;
    const res = await this.drive.files.create({
      requestBody,
      media: { mimeType, body: Readable.from(buffer) },
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
