import { MikroOrmBaseEntityRepository } from '@irtranscripts/core';
import { ProductPrice } from '../product-price.entity';

export class MikroOrmProductPriceRepository extends MikroOrmBaseEntityRepository<ProductPrice> {}
