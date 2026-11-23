import { Body, Controller, HttpStatus, Param, Post, UseGuards, UseInterceptors } from '@nestjs/common';
import { CommandBus } from '@nestjs/cqrs';
import { ApiOperation, ApiResponse } from '@nestjs/swagger';
import {
	IOrganizationCreateInput,
	ITenantCreateInput,
	IUserRegistrationInput,
	PermissionsEnum
} from '@irtranscripts/contracts';
import { CloudMigrateInterceptor } from './../core/interceptors';
import { PermissionGuard, TenantPermissionGuard } from './../shared/guards';
import { Permissions } from './../shared/decorators';
import {
	IRTranscriptsCloudOrganizationMigrateCommand,
	IRTranscriptsCloudTenantMigrateCommand,
	IRTranscriptsCloudUserMigrateCommand
} from './commands';

@UseInterceptors(CloudMigrateInterceptor)
@UseGuards(TenantPermissionGuard, PermissionGuard)
@Permissions(PermissionsEnum.MIGRATE_IRTRANSCRIPTS_CLOUD)
@Controller('/cloud/migrate')
export class IRTranscriptsCloudController {
	constructor(private readonly commandBus: CommandBus) {}

	/**
	 *
	 * @param body
	 * @returns
	 */
	@ApiOperation({ summary: 'Migrate self hosted to irtranscripts cloud hosted' })
	@ApiResponse({
		status: HttpStatus.CREATED,
		description: 'The user has been successfully created in the IRTranscripts cloud.'
	})
	@ApiResponse({
		status: HttpStatus.BAD_REQUEST,
		description: 'Invalid input, The response body may contain clues as to what went wrong'
	})
	@Post()
	async migrateUserToIRTranscriptsCloud(@Body() body: IUserRegistrationInput) {
		return await this.commandBus.execute(new IRTranscriptsCloudUserMigrateCommand(body));
	}

	/**
	 *
	 * @param body
	 * @param token
	 * @returns
	 */
	@ApiOperation({ summary: 'Migrate self hosted tenant into the irtranscripts cloud tenant' })
	@ApiResponse({
		status: HttpStatus.CREATED,
		description: 'The tenant has been successfully created in the IRTranscripts cloud.'
	})
	@ApiResponse({
		status: HttpStatus.BAD_REQUEST,
		description: 'Invalid input, The response body may contain clues as to what went wrong'
	})
	@Post('tenant/:token')
	async migrateTenantToIRTranscriptsCloud(@Body() body: ITenantCreateInput, @Param('token') token: string) {
		return await this.commandBus.execute(new IRTranscriptsCloudTenantMigrateCommand(body, token));
	}

	/**
	 *
	 * @param body
	 * @param token
	 * @returns
	 */
	@ApiOperation({ summary: 'Migrate self hosted organization into the irtranscripts cloud organization' })
	@ApiResponse({
		status: HttpStatus.CREATED,
		description: 'The organization has been successfully created in the IRTranscripts cloud.'
	})
	@ApiResponse({
		status: HttpStatus.BAD_REQUEST,
		description: 'Invalid input, The response body may contain clues as to what went wrong'
	})
	@Post('organization/:token')
	async migrateOrganizationToIRTranscriptsCloud(@Body() body: IOrganizationCreateInput, @Param('token') token: string) {
		return await this.commandBus.execute(new IRTranscriptsCloudOrganizationMigrateCommand(body, token));
	}
}
