import { ICandidate } from '@irtranscripts/contracts';
import { ICommand } from '@nestjs/cqrs';

export class CandidateHiredCommand implements ICommand {
	static readonly type = '[Candidate] Hired';

	constructor(
		public readonly id: ICandidate['id']
	) {}
}
