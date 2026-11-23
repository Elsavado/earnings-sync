import { ICommand } from '@nestjs/cqrs';
import { ID } from '@irtranscripts/contracts';

export class ArchiveDocumentCommand implements ICommand {
	public static readonly type = '[Document] Archive';
	constructor(public readonly id: ID) {}
}
