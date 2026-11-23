import { IntersectionType } from '@nestjs/swagger';
import { IFavoriteCreateInput } from '@irtranscripts/contracts';
import { TenantOrganizationBaseDTO } from './../../core/dto';
import { Favorite } from '../favorite.entity';

/*
 * Make entity record as favorite
 */
export class CreateFavoriteDTO
	extends IntersectionType(TenantOrganizationBaseDTO, Favorite)
	implements IFavoriteCreateInput {}
