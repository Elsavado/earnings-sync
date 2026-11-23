import { ICommand } from '@nestjs/cqrs';
import { ITenant } from '@irtranscripts/contracts';

export class TenantRoleBulkCreateCommand implements ICommand {
	static readonly type = '[Role] Bulk Create';

	constructor(public readonly input: ITenant[]) {}
}
