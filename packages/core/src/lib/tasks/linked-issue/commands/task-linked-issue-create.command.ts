import { ICommand } from '@nestjs/cqrs';
import { ITaskLinkedIssueCreateInput } from '@irtranscripts/contracts';

export class TaskLinkedIssueCreateCommand implements ICommand {
	static readonly type = '[Task Linked Issue] Create';

	constructor(public readonly input: ITaskLinkedIssueCreateInput) {}
}
