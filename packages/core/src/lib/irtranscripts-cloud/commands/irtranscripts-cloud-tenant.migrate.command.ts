import { ICommand } from '@nestjs/cqrs';
import { ITenantCreateInput } from '@irtranscripts/contracts';

export class IRTranscriptsCloudTenantMigrateCommand implements ICommand {
	static readonly type = '[IRTranscripts Cloud] Tenant Migrate';

	constructor(
		public readonly input: ITenantCreateInput,
		public readonly token: string
	) {}
}
