import { IntersectionType } from '@nestjs/swagger';
import { IOrganizationSprintCreateInput } from '@irtranscripts/contracts';
import { TenantOrganizationBaseDTO } from './../../core/dto';
import { OrganizationSprintDTO } from './organization-sprint.dto';

/**
 * Create Organization Sprint DTO request validation
 */
export class CreateOrganizationSprintDTO
	extends IntersectionType(OrganizationSprintDTO, TenantOrganizationBaseDTO)
	implements IOrganizationSprintCreateInput {}
