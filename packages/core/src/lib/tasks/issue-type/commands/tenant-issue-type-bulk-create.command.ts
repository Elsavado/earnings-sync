import { ICommand } from '@nestjs/cqrs';
import { ITenant } from '@irtranscripts/contracts';

export class TenantIssueTypeBulkCreateCommand implements ICommand {
	static readonly type = '[Tenant] Issue Type Bulk Create';

	constructor(public readonly tenants: ITenant[]) {}
}
