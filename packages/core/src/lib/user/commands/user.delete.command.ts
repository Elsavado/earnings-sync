import { ICommand } from '@nestjs/cqrs';
import { ID } from '@irtranscripts/contracts';

export class UserDeleteCommand implements ICommand {
	static readonly type = '[User] Delete Account';

	constructor(public readonly userId: ID) { }
}
