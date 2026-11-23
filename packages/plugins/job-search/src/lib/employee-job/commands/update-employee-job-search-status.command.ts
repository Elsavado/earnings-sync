import { ID, UpdateEmployeeJobsStatistics } from '@irtranscripts/contracts';
import { ICommand } from '@nestjs/cqrs';

export class UpdateEmployeeJobSearchStatusCommand implements ICommand {
	static readonly type = '[Employee] Update Job Search Status';

	constructor(public readonly employeeId: ID, public readonly input: UpdateEmployeeJobsStatistics) {}
}
