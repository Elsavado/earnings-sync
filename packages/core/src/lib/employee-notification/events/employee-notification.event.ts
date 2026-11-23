import { IEvent } from '@nestjs/cqrs';
import { IEmployeeNotificationCreateInput } from '@irtranscripts/contracts';

export class EmployeeCreateNotificationEvent implements IEvent {
	constructor(public readonly input: IEmployeeNotificationCreateInput) {}
}
