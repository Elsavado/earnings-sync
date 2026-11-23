import { MikroOrmBaseEntityRepository } from '@irtranscripts/core';
import { TaxRate } from '../tax-rate.entity';

export class MikroOrmTaxRateRepository extends MikroOrmBaseEntityRepository<TaxRate> {}
