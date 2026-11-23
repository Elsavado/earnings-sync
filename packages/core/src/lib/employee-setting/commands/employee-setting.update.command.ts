import { ICommand } from '@nestjs/cqrs';
import { ID, IEmployeeSettingUpdateInput } from '@irtranscripts/contracts';

export class EmployeeSettingUpdateCommand implements ICommand {
	static readonly type = '[EmployeeSetting] Update';

	constructor(public readonly id: ID, public readonly input: IEmployeeSettingUpdateInput) {}
}
