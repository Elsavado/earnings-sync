import { ICommand } from '@nestjs/cqrs';
import { IDeleteTimeSlot } from '@irtranscripts/contracts';

export class DeleteTimeSlotCommand implements ICommand {
	static readonly type = '[TimeSlot] delete';

	constructor(public readonly options: IDeleteTimeSlot) {}
}
