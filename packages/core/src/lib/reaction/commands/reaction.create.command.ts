import { ICommand } from '@nestjs/cqrs';
import { IReactionCreateInput } from '@irtranscripts/contracts';

export class ReactionCreateCommand implements ICommand {
	static readonly type = '[Reaction] Create';

	constructor(public readonly input: IReactionCreateInput) {}
}
