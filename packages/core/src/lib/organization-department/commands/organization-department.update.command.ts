import { ID, IOrganizationDepartmentCreateInput } from '@irtranscripts/contracts';
import { ICommand } from '@nestjs/cqrs';

export class OrganizationDepartmentUpdateCommand implements ICommand {
	static readonly type = '[OrganizationDepartment] Update';

	constructor(public readonly id: ID, public readonly input: IOrganizationDepartmentCreateInput) {}
}
