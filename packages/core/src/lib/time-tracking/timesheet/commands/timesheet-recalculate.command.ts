import { ICommand } from '@nestjs/cqrs';
import { ID } from '@irtranscripts/contracts';

export class TimesheetRecalculateCommand implements ICommand {
	static readonly type = '[Timesheet] Recalculate';

	constructor(public readonly id: ID) {}
}
