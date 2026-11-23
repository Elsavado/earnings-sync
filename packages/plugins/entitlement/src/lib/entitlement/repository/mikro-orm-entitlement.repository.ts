import { Injectable } from '@nestjs/common';
import { MikroOrmBaseEntityRepository } from '@irtranscripts/core';
import { Entitlement } from '../entitlement.entity';

@Injectable()
export class MikroOrmEntitlementRepository extends MikroOrmBaseEntityRepository<Entitlement> {}
