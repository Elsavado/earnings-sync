import { ICommand } from '@nestjs/cqrs';
import { ID } from '@irtranscripts/contracts';
import { DocumentSettingsDTO } from '../dto';

export class UpdateDocumentSettingsCommand implements ICommand {
	public static readonly type = '[Document Settings] Update';
	constructor(public readonly organizationId: ID, public readonly input: DocumentSettingsDTO) {}
}
