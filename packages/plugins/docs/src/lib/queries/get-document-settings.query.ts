import { IQuery } from '@nestjs/cqrs';
import { ID } from '@irtranscripts/contracts';

export class GetDocumentSettingsQuery implements IQuery {
	public static readonly type = '[Document Settings] Get';
	constructor(public readonly organizationId: ID) {}
}
