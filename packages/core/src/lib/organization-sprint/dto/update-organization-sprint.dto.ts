import { IntersectionType, PartialType } from '@nestjs/swagger';
import { IOrganizationSprintUpdateInput } from '@irtranscripts/contracts';
import { WithoutInitializers } from '@irtranscripts/common';
import { TenantOrganizationBaseDTO } from '../../core/dto';
import { OrganizationSprintDTO } from './organization-sprint.dto';

/**
 * Update Organization Project DTO request validation
 */
export class UpdateOrganizationSprintDTO
	extends WithoutInitializers(IntersectionType(TenantOrganizationBaseDTO, PartialType(OrganizationSprintDTO)))
	implements IOrganizationSprintUpdateInput {}
