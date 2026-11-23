import { IEntitySubscriptionCreateInput } from '@irtranscripts/contracts';
import { ICommand } from '@nestjs/cqrs';

export class EntitySubscriptionCreateCommand implements ICommand {
	static readonly type = '[Subscription] Create';

	constructor(public readonly input: IEntitySubscriptionCreateInput) {}
}
