import { ICommand } from '@nestjs/cqrs';
import { IProductCreateInput } from '@irtranscripts/contracts';

export class ProductUpdateCommand implements ICommand {
	static readonly type = '[Product] Update';

	constructor(
		public readonly id: string,
		public readonly productUpdateRequest: IProductCreateInput
	) {}
}
