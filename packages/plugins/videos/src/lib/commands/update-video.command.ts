import { ICommand } from '@nestjs/cqrs';
import { UpdateVideoDTO } from '../dto';
import { ID } from '@irtranscripts/contracts';

export class UpdateVideoCommand implements ICommand {
	public static readonly type = '[Update] Video';
	constructor(public readonly id: ID, public readonly input: UpdateVideoDTO) {}
}
