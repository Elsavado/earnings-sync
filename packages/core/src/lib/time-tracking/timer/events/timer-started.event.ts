import { IEvent } from '@nestjs/cqrs';
import { ITimeLog } from '@irtranscripts/contracts';

export class TimerStartedEvent implements IEvent {
	constructor(public readonly timeLog: ITimeLog) {}
}
