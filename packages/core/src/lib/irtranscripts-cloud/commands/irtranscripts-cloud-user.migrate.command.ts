import { ICommand } from '@nestjs/cqrs';
import { IUserRegistrationInput } from '@irtranscripts/contracts';

export class IRTranscriptsCloudUserMigrateCommand implements ICommand {
	static readonly type = '[IRTranscripts Cloud] User Migrate';

	constructor(public readonly input: IUserRegistrationInput) {}
}