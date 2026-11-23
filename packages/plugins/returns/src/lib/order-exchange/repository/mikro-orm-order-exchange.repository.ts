import { Injectable } from '@nestjs/common';
import { MikroOrmBaseEntityRepository } from '@irtranscripts/core';
import { OrderExchange } from '../order-exchange.entity';

@Injectable()
export class MikroOrmOrderExchangeRepository extends MikroOrmBaseEntityRepository<OrderExchange> {}
