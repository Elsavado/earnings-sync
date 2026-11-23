import { Injectable } from '@nestjs/common';
import { MikroOrmBaseEntityRepository } from '@irtranscripts/core';
import { OrderLine } from '../order-line.entity';

@Injectable()
export class MikroOrmOrderLineRepository extends MikroOrmBaseEntityRepository<OrderLine> {}