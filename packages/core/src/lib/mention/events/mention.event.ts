import { IEvent } from '@nestjs/cqrs';
import { IMentionCreateInput } from '@irtranscripts/contracts';

export class CreateMentionEvent implements IEvent {
	constructor(public readonly input: IMentionCreateInput) {}
}
