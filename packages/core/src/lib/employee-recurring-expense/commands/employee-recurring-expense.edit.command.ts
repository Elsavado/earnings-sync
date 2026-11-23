import { IEmployeeRecurringExpense, IRecurringExpenseEditInput } from '@irtranscripts/contracts';
import { ICommand } from '@nestjs/cqrs';

export class EmployeeRecurringExpenseEditCommand implements ICommand {
	static readonly type = '[EmployeeRecurringExpense] Edit';

	constructor(
		public readonly id: IEmployeeRecurringExpense['id'],
		public readonly input: IRecurringExpenseEditInput
	) {}
}
