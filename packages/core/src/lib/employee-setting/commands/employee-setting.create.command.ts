import { ICommand } from '@nestjs/cqrs';
import { IEmployeeSettingCreateInput } from '@irtranscripts/contracts';

export class EmployeeSettingCreateCommand implements ICommand {
	static readonly type = '[EmployeeSetting] Create';

	constructor(public readonly input: IEmployeeSettingCreateInput) {}
}
