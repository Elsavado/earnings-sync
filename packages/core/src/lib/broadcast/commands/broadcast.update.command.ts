import { ICommand } from '@nestjs/cqrs';
import { IBroadcastUpdateInput, ID } from '@irtranscripts/contracts';

export class BroadcastUpdateCommand implements ICommand {
	static readonly type = '[Broadcast] Update';

	constructor(
		public readonly id: ID,
		public readonly input: IBroadcastUpdateInput
	) {}
}
