import { ICommand } from '@nestjs/cqrs';
import { ITenant } from '@irtranscripts/contracts';

export class TenantTaskSizeBulkCreateCommand implements ICommand {
	static readonly type = '[Tenant] Task Size Bulk Create';

	constructor(
		public readonly tenants: ITenant[]
	) { }
}
