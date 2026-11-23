import { ICommand } from '@nestjs/cqrs';
import { ITag, ITagUpdateInput } from '@irtranscripts/contracts';

export class TagUpdateCommand implements ICommand {
	static readonly type = '[Tag] Update Tag';

	constructor(
		public readonly id: ITag['id'],
		public readonly input: ITagUpdateInput
	) { }
}
