/**
 * MikroORM repository for StockReservation.
 */
import { MikroOrmBaseEntityRepository } from '@irtranscripts/core';
import { StockReservation } from '../stock-reservation.entity';

export class MikroOrmStockReservationRepository extends MikroOrmBaseEntityRepository<StockReservation> {}
