import { ICommand } from '@nestjs/cqrs';
import { IOrganizationCreateInput } from '@irtranscripts/contracts';

export class IRTranscriptsCloudOrganizationMigrateCommand implements ICommand {
	static readonly type = '[IRTranscripts Cloud] Organization Migrate';

	constructor(
		public readonly input: IOrganizationCreateInput,
		public readonly token: string
	) {}
}
