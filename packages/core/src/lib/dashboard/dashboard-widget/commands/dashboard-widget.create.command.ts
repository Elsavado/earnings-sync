import { ICommand } from '@nestjs/cqrs';
import { IDashboardWidgetCreateInput } from '@irtranscripts/contracts';

export class DashboardWidgetCreateCommand implements ICommand {
	static readonly type = '[DashboardWidget] Create';

	constructor(public readonly input: IDashboardWidgetCreateInput) {}
}
