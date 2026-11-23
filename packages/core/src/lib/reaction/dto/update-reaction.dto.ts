import { IntersectionType, PickType } from '@nestjs/swagger';
import { IReactionUpdateInput } from '@irtranscripts/contracts';
import { Reaction } from '../reaction.entity';
import { TenantOrganizationBaseDTO } from '../../core/dto';

/**
 * Update Reaction data validation request DTO
 */
export class UpdateReactionDTO
	extends IntersectionType(TenantOrganizationBaseDTO, PickType(Reaction, ['emoji'] as const))
	implements IReactionUpdateInput {}
