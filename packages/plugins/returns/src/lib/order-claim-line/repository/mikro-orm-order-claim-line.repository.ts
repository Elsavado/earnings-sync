import { Injectable } from '@nestjs/common';
import { MikroOrmBaseEntityRepository } from '@irtranscripts/core';
import { OrderClaimLine } from '../order-claim-line.entity';

@Injectable()
export class MikroOrmOrderClaimLineRepository extends MikroOrmBaseEntityRepository<OrderClaimLine> {}
