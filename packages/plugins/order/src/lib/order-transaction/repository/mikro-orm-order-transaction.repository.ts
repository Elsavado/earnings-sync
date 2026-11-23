import { Injectable } from '@nestjs/common';
import { MikroOrmBaseEntityRepository } from '@irtranscripts/core';
import { OrderTransaction } from '../order-transaction.entity';

@Injectable()
export class MikroOrmOrderTransactionRepository extends MikroOrmBaseEntityRepository<OrderTransaction> {}