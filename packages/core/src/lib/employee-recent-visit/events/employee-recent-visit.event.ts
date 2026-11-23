import { IEvent } from '@nestjs/cqrs';
import { IEmployeeRecentVisitInput } from '@irtranscripts/contracts';

export class EmployeeRecentVisitEvent implements IEvent {
	constructor(public readonly input: IEmployeeRecentVisitInput) {}
}
