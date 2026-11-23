import { Injectable } from '@nestjs/common';
import { MikroOrmBaseEntityRepository } from '@irtranscripts/core';
import { EntitlementActivation } from '../entitlement-activation.entity';

@Injectable()
export class MikroOrmEntitlementActivationRepository extends MikroOrmBaseEntityRepository<EntitlementActivation> {}
