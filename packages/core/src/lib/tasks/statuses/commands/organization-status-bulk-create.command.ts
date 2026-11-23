import { ICommand } from '@nestjs/cqrs';
import { IOrganization } from '@irtranscripts/contracts';

export class OrganizationStatusBulkCreateCommand implements ICommand {
	static readonly type = '[Organization Status] Bulk Create';

	constructor(
		public readonly input: IOrganization
	) {}
}
