import { ICommand } from '@nestjs/cqrs';
import { ISubmitTimesheetInput } from '@irtranscripts/contracts';

export class TimesheetSubmitCommand implements ICommand {
	static readonly type = '[Timesheet] Submit';

	constructor(
		public readonly input: ISubmitTimesheetInput
	) {}
}
