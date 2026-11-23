import { ICommand } from '@nestjs/cqrs';
import { ID } from '@irtranscripts/contracts';

export class RecoverDocumentCommand implements ICommand {
	public static readonly type = '[Document] Recover';
	constructor(public readonly id: ID) {}
}
