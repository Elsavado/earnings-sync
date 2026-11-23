import { Body, Controller, Get, HttpCode, HttpStatus, Param, Post, Put, Query, UseGuards } from '@nestjs/common';
import { ApiBearerAuth, ApiOperation, ApiProperty, ApiPropertyOptional, ApiTags } from '@nestjs/swagger';
import { Type } from 'class-transformer';
import { ArrayMaxSize, IsArray, IsBoolean, IsString, IsUUID, MaxLength, ValidateIf, ValidateNested } from 'class-validator';
import { ID, PermissionsEnum } from '@irtranscripts/contracts';
import { PermissionGuard, Permissions, TenantPermissionGuard, UseValidationPipe, UUIDValidationPipe } from '@irtranscripts/core';
import { EVER_WORKS_ROUTE_PREFIX } from '../ever-works.constants';
import { EverWorksAgentsService } from './ever-works-agents.service';
import { EverWorksPeopleService } from './ever-works-people.service';

export class EverWorksPersonLinkDto {
	@ApiProperty({ description: 'Ever Works user id (a member of the mapped organization).' })
	@IsString()
	@MaxLength(64)
	readonly ewUserId!: string;

	@ApiProperty({ description: 'IRTranscripts employee id (an active person of this organization).' })
	@IsUUID()
	readonly employeeId!: string;
}

export class EverWorksInviteToIRTranscriptsDto {
	@ApiProperty({ description: 'Ever Works user id of a member of the mapped organization with no IRTranscripts person yet.' })
	@IsString()
	@MaxLength(64)
	readonly ewUserId!: string;

	@ApiPropertyOptional({
		description: "The tenant's Employee role (the default): the only role whose acceptance creates an employee the People tab can pair."
	})
	@ValidateIf((_o, v) => v !== undefined)
	@IsUUID()
	readonly roleId?: string;
}

export class EverWorksInviteToEverWorksDto {
	@ApiProperty({ description: 'IRTranscripts employee id of an active person of this organization with no Ever Works member yet.' })
	@IsUUID()
	readonly employeeId!: string;
}

export class EverWorksPeopleDecisionDto {
	@ApiPropertyOptional({ type: [EverWorksPersonLinkDto] })
	@ValidateIf((_o, v) => v !== undefined)
	@IsArray()
	@ArrayMaxSize(5000)
	@ValidateNested({ each: true })
	@Type(() => EverWorksPersonLinkDto)
	readonly links?: EverWorksPersonLinkDto[];

	@ApiPropertyOptional({ type: [String], description: 'Ever Works user ids whose link is removed.' })
	@ValidateIf((_o, v) => v !== undefined)
	@IsArray()
	@ArrayMaxSize(5000)
	@IsString({ each: true })
	@MaxLength(64, { each: true })
	readonly unlinks?: string[];

	@ApiPropertyOptional({ description: 'Link every verified-email suggestion.' })
	@ValidateIf((_o, v) => v !== undefined)
	@IsBoolean()
	readonly acceptSuggestions?: boolean;
}

/**
 * `/api/integration/ever-works/mappings/:integrationTenantId/{people,agents}` (plan 06 G-P1-6). Same guards
 * and organization-membership check as every management route.
 */
@ApiTags('Ever Works Integration')
@ApiBearerAuth()
@UseGuards(TenantPermissionGuard, PermissionGuard)
@Controller(`${EVER_WORKS_ROUTE_PREFIX}/mappings/:integrationTenantId`)
export class EverWorksPeopleController {
	constructor(
		private readonly people: EverWorksPeopleService,
		private readonly agents: EverWorksAgentsService
	) {}

	@Get('/people')
	@Permissions(PermissionsEnum.INTEGRATION_VIEW)
	@ApiOperation({ summary: 'Ever Works members with their link or a verified-email suggestion, and the unmatched IRTranscripts people.' })
	listPeople(@Param('integrationTenantId', UUIDValidationPipe) id: ID, @Query('organizationId') organizationId?: ID) {
		return this.people.people(id, organizationId);
	}

	@Put('/people')
	@Permissions(PermissionsEnum.INTEGRATION_EDIT)
	@UseValidationPipe({ whitelist: true })
	@ApiOperation({ summary: 'Confirm or remove people links, or accept every suggestion (nothing is linked silently).' })
	decide(@Param('integrationTenantId', UUIDValidationPipe) id: ID, @Body() dto: EverWorksPeopleDecisionDto, @Query('organizationId') organizationId?: ID) {
		return this.people.decide(id, dto, organizationId);
	}

	@Post('/people/invite-to-irtranscripts')
	@Permissions(PermissionsEnum.INTEGRATION_EDIT)
	@HttpCode(HttpStatus.OK)
	@UseValidationPipe({ whitelist: true })
	@ApiOperation({
		summary: 'Invite an Ever Works member with no IRTranscripts person as an employee (the platform invite flow; needs ORG_INVITE_EDIT too).'
	})
	inviteToIRTranscripts(@Param('integrationTenantId', UUIDValidationPipe) id: ID, @Body() dto: EverWorksInviteToIRTranscriptsDto, @Query('organizationId') organizationId?: ID) {
		return this.people.inviteToIRTranscripts(id, { ewUserId: dto.ewUserId, roleId: dto.roleId as ID | undefined }, organizationId);
	}

	@Post('/people/invite-to-ever-works')
	@Permissions(PermissionsEnum.INTEGRATION_EDIT)
	@HttpCode(HttpStatus.OK)
	@UseValidationPipe({ whitelist: true })
	@ApiOperation({
		summary: 'Invite a IRTranscripts person with no Ever Works member into the mapped Ever Works organization (needs ORG_INVITE_EDIT too).'
	})
	inviteToEverWorks(@Param('integrationTenantId', UUIDValidationPipe) id: ID, @Body() dto: EverWorksInviteToEverWorksDto, @Query('organizationId') organizationId?: ID) {
		return this.people.inviteToEverWorks(id, { employeeId: dto.employeeId as ID }, organizationId);
	}

	@Get('/agents')
	@Permissions(PermissionsEnum.INTEGRATION_VIEW)
	listAgents(@Param('integrationTenantId', UUIDValidationPipe) id: ID, @Query('organizationId') organizationId?: ID) {
		return this.agents.list(id, organizationId);
	}

	@Post('/agents/import')
	@Permissions(PermissionsEnum.INTEGRATION_EDIT)
	@HttpCode(HttpStatus.OK)
	@ApiOperation({ summary: 'Provision every Ever Works agent of the mapped organization as an agent employee.' })
	importAgents(@Param('integrationTenantId', UUIDValidationPipe) id: ID, @Query('organizationId') organizationId?: ID) {
		return this.agents.importAll(id, organizationId);
	}
}
