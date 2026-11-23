import { Injectable } from '@nestjs/common';
import { MikroOrmBaseEntityRepository } from '@irtranscripts/core';
import { SubscriptionPlan } from '../subscription-plan.entity';

@Injectable()
export class MikroOrmSubscriptionPlanRepository extends MikroOrmBaseEntityRepository<SubscriptionPlan> {}
