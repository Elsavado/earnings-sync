import { IEvent } from '@nestjs/cqrs';
import { ITimerStatus } from '@irtranscripts/contracts';

export class TimerStatusUpdatedEvent implements IEvent {
	constructor(public readonly status: ITimerStatus) {}
}
