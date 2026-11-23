import { ICommand } from '@nestjs/cqrs';
import { ITimerToggleInput } from '@irtranscripts/contracts';

export class StartTimerCommand implements ICommand {
	constructor(public readonly input: ITimerToggleInput) {}
}
