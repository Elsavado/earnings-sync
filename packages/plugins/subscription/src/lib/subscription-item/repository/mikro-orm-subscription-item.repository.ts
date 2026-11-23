import { Injectable } from '@nestjs/common';
import { MikroOrmBaseEntityRepository } from '@irtranscripts/core';
import { SubscriptionItem } from '../subscription-item.entity';

@Injectable()
export class MikroOrmSubscriptionItemRepository extends MikroOrmBaseEntityRepository<SubscriptionItem> {}
