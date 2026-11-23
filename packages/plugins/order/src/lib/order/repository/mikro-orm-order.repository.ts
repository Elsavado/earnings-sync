import { Injectable } from '@nestjs/common';
import { MikroOrmBaseEntityRepository } from '@irtranscripts/core';
import { Order } from '../order.entity';

@Injectable()
export class MikroOrmOrderRepository extends MikroOrmBaseEntityRepository<Order> {}