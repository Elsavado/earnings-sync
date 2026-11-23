import { ICommand } from '@nestjs/cqrs';
import { ID } from '@irtranscripts/contracts';

export class ScheduleTimeSlotEntriesCommand implements ICommand {
	static readonly type = 'Adjust [TimeSlot] Entries';

	constructor(
		public readonly organizationId: ID,
		public readonly tenantId: ID
	) {}
}
