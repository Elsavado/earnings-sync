import { Injectable } from '@nestjs/common';
import { MikroOrmBaseEntityRepository } from '@irtranscripts/core';
import { FulfillmentLine } from '../fulfillment-line.entity';

@Injectable()
export class MikroOrmFulfillmentLineRepository extends MikroOrmBaseEntityRepository<FulfillmentLine> {}