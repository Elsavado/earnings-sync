import { IEvent } from '@nestjs/cqrs';
import { IActivityLogInput } from '@irtranscripts/contracts';

export class ActivityLogEvent implements IEvent {
	constructor(public readonly input: IActivityLogInput) {}
}
