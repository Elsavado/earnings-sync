import { IMatchingCriterions } from '@irtranscripts/contracts';
import { ICommand } from '@nestjs/cqrs';

export class SavePresetCriterionCommand implements ICommand {
	static readonly type = '[JobPresetCriterion] Create';

	constructor(public readonly input?: IMatchingCriterions) {}
}
