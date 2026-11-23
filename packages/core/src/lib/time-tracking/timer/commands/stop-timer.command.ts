import { ICommand } from '@nestjs/cqrs';
import { ITimerToggleInput } from '@irtranscripts/contracts';

export class StopTimerCommand implements ICommand {
	constructor(public readonly input: ITimerToggleInput) {}
}
