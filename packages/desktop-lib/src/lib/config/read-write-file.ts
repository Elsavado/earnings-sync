import { accessSync, constants, readFileSync, writeFileSync } from 'fs';
import { IPathWindow, IReadWriteFile } from '../interfaces';

export class ReadWriteFile implements IReadWriteFile {
	private _path: IPathWindow;

	constructor(readonly path: IPathWindow) {
		this._path = path;
	}

	public read(): string {
		if (!this.hasDirectoryAccess) {
			return;
		}
		try {
			console.log(`Reading file ${this._path.irtranscriptsUi}`);
			return readFileSync(this._path.irtranscriptsUi, 'utf8');
		} catch (e) {
			console.error('Cannot read file');
		}
	}

	public get hasDirectoryAccess(): boolean {
		try {
			accessSync(this._path.dir, constants.W_OK);
			return true;
		} catch (e) {
			console.error('Cannot access directory');
			return false;
		}
	}

	public write(fileContent: string): void {
		if (!this.hasDirectoryAccess) {
			return;
		}

		try {
			console.log(`Writing file ${this._path.irtranscriptsUi}`);
			writeFileSync(this._path.irtranscriptsUi, fileContent);
		} catch (error) {
			console.log('Cannot change html file', error);
		}
	}
}
