import { Injectable } from '@nestjs/common';
import { MikroOrmBaseEntityRepository } from '@irtranscripts/core';
import { OrderCreditLine } from '../order-credit-line.entity';

@Injectable()
export class MikroOrmOrderCreditLineRepository extends MikroOrmBaseEntityRepository<OrderCreditLine> {}