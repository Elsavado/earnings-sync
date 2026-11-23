import { ICommand } from '@nestjs/cqrs';
import { IOrganizationTeam } from '@irtranscripts/contracts';

export class OrganizationTeamTaskSizeBulkCreateCommand implements ICommand {
	static readonly type = '[Organization Team] Task Size Bulk Create';

	constructor(
		public readonly input: IOrganizationTeam
	) { }
}
