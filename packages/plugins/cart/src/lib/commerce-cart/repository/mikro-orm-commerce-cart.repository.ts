import { Injectable } from '@nestjs/common';
import { MikroOrmBaseEntityRepository } from '@irtranscripts/core';
import { CommerceCart } from '../commerce-cart.entity';

@Injectable()
export class MikroOrmCommerceCartRepository extends MikroOrmBaseEntityRepository<CommerceCart> {}
