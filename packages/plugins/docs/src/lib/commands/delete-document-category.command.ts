import { ICommand } from '@nestjs/cqrs';
import { ID } from '@irtranscripts/contracts';

export class DeleteDocumentCategoryCommand implements ICommand {
	public static readonly type = '[Document Category] Delete';
	constructor(public readonly id: ID) {}
}
