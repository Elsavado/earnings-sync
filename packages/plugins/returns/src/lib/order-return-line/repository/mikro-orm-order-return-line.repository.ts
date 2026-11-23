import { Injectable } from '@nestjs/common';
import { MikroOrmBaseEntityRepository } from '@irtranscripts/core';
import { OrderReturnLine } from '../order-return-line.entity';

@Injectable()
export class MikroOrmOrderReturnLineRepository extends MikroOrmBaseEntityRepository<OrderReturnLine> {}
