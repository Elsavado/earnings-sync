/**
 * MikroORM repository for StockAlert.
 */
import { MikroOrmBaseEntityRepository } from '@irtranscripts/core';
import { StockAlert } from '../stock-alert.entity';

export class MikroOrmStockAlertRepository extends MikroOrmBaseEntityRepository<StockAlert> {}
