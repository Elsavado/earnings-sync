import { ICommand } from '@nestjs/cqrs';
import { IIntegrationEntitySettingTied, IIntegrationTenant } from '@irtranscripts/contracts';

export class IntegrationEntitySettingTiedUpdateCommand implements ICommand {
	static readonly type = '[Integration Entity Setting Tied] Update By Integration';

	constructor(
		public readonly integrationId: IIntegrationTenant['id'],
		public readonly input: IIntegrationEntitySettingTied | IIntegrationEntitySettingTied[],
	) { }
}
