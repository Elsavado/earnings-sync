import { MikroOrmBaseEntityRepository } from '@irtranscripts/core';
import { TaxCategory } from '../tax-category.entity';

export class MikroOrmTaxCategoryRepository extends MikroOrmBaseEntityRepository<TaxCategory> {}
