import { Module } from '@nestjs/common';
import { CqrsModule } from '@nestjs/cqrs';
import { IRTranscriptsAIModule } from '@irtranscripts/plugin-integration-ai';
import { EmployeeModule, IntegrationTenantModule, RolePermissionModule, TenantModule } from '@irtranscripts/core';
import { EmployeeJobPostService } from './employee-job.service';
import { EmployeeJobPostController } from './employee-job.controller';
import { CommandHandlers } from './commands';
import { QueryHandlers } from './queries';

@Module({
	imports: [
		EmployeeModule,
		IntegrationTenantModule,
		TenantModule,
		RolePermissionModule,
		IRTranscriptsAIModule.forRoot(),
		CqrsModule
	],
	controllers: [EmployeeJobPostController],
	providers: [EmployeeJobPostService, ...CommandHandlers, ...QueryHandlers]
})
export class EmployeeJobPostModule {}
