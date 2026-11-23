import { ICommand } from '@nestjs/cqrs';
import { ID } from '@irtranscripts/contracts';
import { UpdateExtractedTextDTO } from '../dto';

export class UpdateExtractedTextCommand implements ICommand {
	public static readonly type = '[Document] Update Extracted Text';
	constructor(public readonly id: ID, public readonly input: UpdateExtractedTextDTO) {}
}
