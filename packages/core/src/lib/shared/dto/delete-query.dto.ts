import { PickType } from '@nestjs/swagger';
import { IBasePerTenantAndOrganizationEntityModel } from '@irtranscripts/contracts';
import { TenantOrganizationBaseDTO } from '../../core/dto/tenant-organization-base.dto';

/**
 * Delete query DTO
 *
 */
export class DeleteQueryDTO<T>
	extends PickType(TenantOrganizationBaseDTO, ['organizationId', 'tenantId'])
	implements IBasePerTenantAndOrganizationEntityModel {}
