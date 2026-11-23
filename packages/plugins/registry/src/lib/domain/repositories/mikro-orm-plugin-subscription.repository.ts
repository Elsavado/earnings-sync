import { MikroOrmBaseEntityRepository } from '@irtranscripts/core';
import { PluginSubscription } from '../entities/plugin-subscription.entity';

export class MikroOrmPluginSubscriptionRepository extends MikroOrmBaseEntityRepository<PluginSubscription> {}
