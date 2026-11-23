import { IntersectionType } from '@nestjs/swagger';
import { IResourceLinkCreateInput } from '@irtranscripts/contracts';
import { TenantOrganizationBaseDTO } from '../../core/dto';
import { ResourceLink } from '../resource-link.entity';

/**
 * Create ResourceLink data validation request DTO
 */
export class CreateResourceLinkDTO
	extends IntersectionType(TenantOrganizationBaseDTO, ResourceLink)
	implements IResourceLinkCreateInput {}
