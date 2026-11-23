import { Injectable } from '@nestjs/common';
import { MikroOrmBaseEntityRepository } from '@irtranscripts/core';
import { SellerOffering } from '../seller-offering.entity';

/**
 * The MikroORM side of the SellerOffering aggregate.
 */
@Injectable()
export class MikroOrmSellerOfferingRepository extends MikroOrmBaseEntityRepository<SellerOffering> {}