import { CommandHandler, ICommandHandler } from '@nestjs/cqrs';
import { IRTranscriptsCloudService } from '../../irtranscripts-cloud.service';
import { IRTranscriptsCloudOrganizationMigrateCommand } from './../irtranscripts-cloud-organization.migrate.command';

@CommandHandler(IRTranscriptsCloudOrganizationMigrateCommand)
export class IRTranscriptsCloudOrganizationMigrateHandler implements ICommandHandler<IRTranscriptsCloudOrganizationMigrateCommand> {

	constructor(
		private readonly irtranscriptsCloudService: IRTranscriptsCloudService
	) {}

	public async execute(command: IRTranscriptsCloudOrganizationMigrateCommand): Promise<any> {
		const { input, token } = command;
		return this.irtranscriptsCloudService.migrateOrganization(input, token);
	}
}
