import { ITaskViewCreateInput } from '@irtranscripts/contracts';
import { ICommand } from '@nestjs/cqrs';

export class TaskViewCreateCommand implements ICommand {
	static readonly type = '[Task View] Create';

	constructor(public readonly input: ITaskViewCreateInput) {}
}
