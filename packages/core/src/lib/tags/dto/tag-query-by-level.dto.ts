import { IntersectionType, PartialType } from '@nestjs/swagger';
import { ITagFindInput } from '@irtranscripts/contracts';
import { TenantOrganizationBaseDTO } from '../../core/dto';
import { RelationsQueryDTO } from '../../shared/dto';

export class TagQueryByLevelDTO
	extends IntersectionType(PartialType(TenantOrganizationBaseDTO), RelationsQueryDTO)
	implements ITagFindInput {}
