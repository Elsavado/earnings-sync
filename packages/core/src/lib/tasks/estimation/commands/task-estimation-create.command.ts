import { ICommand } from '@nestjs/cqrs';
import { ITaskEstimationCreateInput } from '@irtranscripts/contracts';

export class TaskEstimationCreateCommand implements ICommand {
	static readonly type = '[Task Estimation] Create Task Estimation';

	constructor(public readonly input: ITaskEstimationCreateInput) {}
}
