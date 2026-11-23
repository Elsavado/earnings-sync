import { ICommand } from '@nestjs/cqrs';
import { IScreenshotUpdateInput } from '@irtranscripts/contracts';

export class ScreenshotUpdateCommand implements ICommand {
	static readonly type = '[Screenshot] Update Screenshot';

	constructor(public readonly input: IScreenshotUpdateInput) {}
}
