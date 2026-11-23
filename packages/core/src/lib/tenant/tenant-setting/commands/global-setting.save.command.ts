import { ICommand } from '@nestjs/cqrs';
import { ITenantSetting } from '@irtranscripts/contracts';

export class GlobalSettingSaveCommand implements ICommand {
	static readonly type = '[Global] Setting Save';

	constructor(public readonly input: ITenantSetting) {}
}
