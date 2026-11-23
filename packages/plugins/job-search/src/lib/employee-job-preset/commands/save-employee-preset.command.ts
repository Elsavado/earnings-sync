import { IEmployeePresetInput } from '@irtranscripts/contracts';
import { ICommand } from '@nestjs/cqrs';

export class SaveEmployeePresetCommand implements ICommand {
	static readonly type = '[EmployeePreset] Create';

	constructor(public readonly input?: IEmployeePresetInput) {}
}
