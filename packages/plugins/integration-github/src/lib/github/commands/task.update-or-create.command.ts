import { IGetTaskOptions, ITask } from '@irtranscripts/contracts';

export class GithubTaskUpdateOrCreateCommand {
	constructor(public readonly task: ITask, public readonly options: IGetTaskOptions) {}
}
