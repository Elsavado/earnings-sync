import { ICommand } from '@nestjs/cqrs';
import { ID, IEmployeeNotificationSettingUpdateInput } from '@irtranscripts/contracts';

export class EmployeeNotificationSettingUpdateCommand implements ICommand {
	static readonly type = '[EmployeeNotificationSetting] Update';

	constructor(public readonly id: ID, public readonly input: IEmployeeNotificationSettingUpdateInput) {}
}
