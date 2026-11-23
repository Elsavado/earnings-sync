import { ApiProperty } from '@nestjs/swagger';
import { IsBoolean } from 'class-validator';
import { UpdateEmployeeJobsStatistics } from '@irtranscripts/contracts';
import { TenantOrganizationBaseDTO } from '@irtranscripts/core';

/**
 * Employee Job Statistic DTO
 */
export class EmployeeJobStatisticDTO extends TenantOrganizationBaseDTO implements UpdateEmployeeJobsStatistics {
	@ApiProperty({ type: () => Boolean })
	@IsBoolean()
	isJobSearchActive: boolean;
}
