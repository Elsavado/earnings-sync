import { ICommand } from '@nestjs/cqrs';
import { ITenant } from '@irtranscripts/contracts';

export class TenantVersionBulkCreateCommand implements ICommand {
	static readonly type = '[Tenant Version] Bulk Create';

	constructor(public readonly tenants: ITenant[]) {}
}
