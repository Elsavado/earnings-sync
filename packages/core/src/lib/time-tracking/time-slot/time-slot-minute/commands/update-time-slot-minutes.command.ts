import { ICommand } from '@nestjs/cqrs';
import { ID, ITimeSlotMinute } from '@irtranscripts/contracts';

export class UpdateTimeSlotMinutesCommand implements ICommand {
	static readonly type = '[TimeSlotMinutes] update';

	constructor(public readonly id: ID, public readonly input: ITimeSlotMinute) {}
}
