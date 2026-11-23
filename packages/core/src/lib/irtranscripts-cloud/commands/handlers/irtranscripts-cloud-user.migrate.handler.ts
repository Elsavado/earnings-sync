import { BadRequestException } from '@nestjs/common';
import { CommandHandler, ICommandHandler } from '@nestjs/cqrs';
import { switchMap, catchError } from 'rxjs/operators';
import { IRTranscriptsCloudService } from '../../irtranscripts-cloud.service';
import { IRTranscriptsCloudUserMigrateCommand } from './../irtranscripts-cloud-user.migrate.command';

@CommandHandler(IRTranscriptsCloudUserMigrateCommand)
export class IRTranscriptsCloudUserMigrateHandler implements ICommandHandler<IRTranscriptsCloudUserMigrateCommand> {

	constructor(
		private readonly irtranscriptsCloudService: IRTranscriptsCloudService
	) {}

	public async execute(command: IRTranscriptsCloudUserMigrateCommand): Promise<any> {
		const { input } = command;
		return this.irtranscriptsCloudService.migrateUser(input).pipe(
			switchMap((response: any) => {
				if (response && response.data) {
					const { data } = response;
					const { password } = input;
					return this.irtranscriptsCloudService.extractToken({
						email: data.email,
						password
					});
				}
			}),
			catchError((error) => {
				console.log('Bad Promise:', error);
				throw new BadRequestException(error);
			})
		);
	}
}
