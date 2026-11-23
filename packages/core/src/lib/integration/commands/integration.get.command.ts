import { ICommand } from '@nestjs/cqrs';
import { IIntegrationFilter } from '@irtranscripts/contracts';

export class IntegrationGetCommand implements ICommand {
	static readonly type = '[Integration] Get Integrations';

	constructor(public readonly input: IIntegrationFilter) {}
}
