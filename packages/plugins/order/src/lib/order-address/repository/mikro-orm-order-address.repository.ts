import { Injectable } from '@nestjs/common';
import { MikroOrmBaseEntityRepository } from '@irtranscripts/core';
import { OrderAddress } from '../order-address.entity';

@Injectable()
export class MikroOrmOrderAddressRepository extends MikroOrmBaseEntityRepository<OrderAddress> {}