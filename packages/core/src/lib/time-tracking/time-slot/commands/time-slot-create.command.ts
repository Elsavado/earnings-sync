import { ICommand } from '@nestjs/cqrs';
import { ITimeSlotCreateInput } from '@irtranscripts/contracts';

export class TimeSlotCreateCommand implements ICommand {
	static readonly type = '[TimeSlot] Create TimeSlot';

	constructor(public readonly input: ITimeSlotCreateInput) {}
}
