import { IQueryHandler, QueryHandler } from '@nestjs/cqrs';
import { IRTranscriptsAIService } from '@irtranscripts/plugin-integration-ai';
import { IEmployee, IPagination, PermissionsEnum } from '@irtranscripts/contracts';
import { EmployeeService, RequestContext } from '@irtranscripts/core';
import { GetEmployeeJobStatisticsQuery } from '../get-employee-job-statistics.query';

@QueryHandler(GetEmployeeJobStatisticsQuery)
export class GetEmployeeJobStatisticsHandler implements IQueryHandler<GetEmployeeJobStatisticsQuery> {
	/**
	 *
	 * @param employeeService
	 * @param irtranscriptsAIService
	 */
	constructor(private readonly employeeService: EmployeeService, private readonly irtranscriptsAIService: IRTranscriptsAIService) {}

	/**
	 * Executes the GetEmployeeJobStatisticsQuery to fetch paginated employee data
	 * and augment it with additional statistics.
	 *
	 * @param query - The query containing options for pagination.
	 * @returns A Promise resolving to an IPagination<IEmployee> with augmented data.
	 */
	public async execute(query: GetEmployeeJobStatisticsQuery): Promise<IPagination<IEmployee>> {
		const { options } = query;

		// Check for permission CHANGE_SELECTED_EMPLOYEE
		if (!RequestContext.hasPermission(PermissionsEnum.CHANGE_SELECTED_EMPLOYEE)) {
			// Filter by current employee ID if the permission is not present. A caller with no employee
			// identity sees nothing — assigning null here used to drop the predicate and page through
			// every employee of the tenant.
			const employeeId = RequestContext.currentEmployeeId();
			if (!employeeId) {
				return { items: [], total: 0 };
			}
			options.where.id = employeeId;
		}

		// Use Promise.all for concurrent requests
		const [paginationResult, employeesStatistics] = await Promise.all([
			this.employeeService.paginate(options),
			this.irtranscriptsAIService.getEmployeesStatistics()
		]);

		let { items, total } = paginationResult;

		// Create a map for faster lookup
		const employeesStatisticsById = new Map<string, any>(
			employeesStatistics.map((statistic: any) => [statistic.employeeId, statistic])
		);

		// Combine mappings into a single map function
		items = items.map((employee: IEmployee) => ({
			...employee,
			...(employeesStatisticsById.get(employee.id) || {}) // Use empty object if not found
		}));

		return { items, total };
	}
}
