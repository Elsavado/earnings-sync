import { Injectable } from '@nestjs/common';
import { MikroOrmBaseEntityRepository } from '@irtranscripts/core';
import { SubscriptionBilling } from '../subscription-billing.entity';

@Injectable()
export class MikroOrmSubscriptionBillingRepository extends MikroOrmBaseEntityRepository<SubscriptionBilling> {}
