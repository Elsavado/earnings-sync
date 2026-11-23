import { ICommand } from '@nestjs/cqrs';
import { IIntegrationMapSyncEntityInput } from '@irtranscripts/contracts';

export class IntegrationMapSyncEntityCommand implements ICommand {
	static readonly type = '[Integration Map] Sync Entity';

	constructor(
		public readonly input: IIntegrationMapSyncEntityInput
	) { }
}
