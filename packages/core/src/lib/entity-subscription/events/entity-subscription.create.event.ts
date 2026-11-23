import { IEvent } from '@nestjs/cqrs';
import { IEntitySubscriptionCreateInput } from '@irtranscripts/contracts';

export class CreateEntitySubscriptionEvent implements IEvent {
	constructor(readonly input: IEntitySubscriptionCreateInput) {}
}
