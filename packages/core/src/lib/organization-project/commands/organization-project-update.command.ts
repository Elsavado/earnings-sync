import { ICommand } from '@nestjs/cqrs';
import { ID, IOrganizationProjectUpdateInput } from '@irtranscripts/contracts';

export class OrganizationProjectUpdateCommand implements ICommand {
	static readonly type = '[Organization Project] Update';

	constructor(readonly id: ID, readonly input: IOrganizationProjectUpdateInput) {}
}
