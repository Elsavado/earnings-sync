import { MikroOrmBaseEntityRepository } from '@irtranscripts/core';
import { ZapierWebhookSubscription } from '../zapier-webhook-subscription.entity';

export class MikroOrmZapierWebhookSubscriptionRepository extends MikroOrmBaseEntityRepository<ZapierWebhookSubscription> { }
