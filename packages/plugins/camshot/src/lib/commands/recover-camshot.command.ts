import { ICommand } from '@nestjs/cqrs';
import { ID } from '@irtranscripts/contracts';

export class RecoverCamshotCommand implements ICommand {
	constructor(public readonly id: ID) { }
}
