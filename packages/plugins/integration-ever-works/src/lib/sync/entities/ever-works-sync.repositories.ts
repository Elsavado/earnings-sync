import { Injectable } from '@nestjs/common';
import { MikroOrmBaseEntityRepository } from '@irtranscripts/core';
import type { EverWorksEntityLink, EverWorksInboundEvent, EverWorksOutboundChange, EverWorksSyncLog } from './ever-works-sync.entities';

@Injectable()
export class MikroOrmEverWorksEntityLinkRepository extends MikroOrmBaseEntityRepository<EverWorksEntityLink> {}

@Injectable()
export class MikroOrmEverWorksInboundEventRepository extends MikroOrmBaseEntityRepository<EverWorksInboundEvent> {}

@Injectable()
export class MikroOrmEverWorksOutboundChangeRepository extends MikroOrmBaseEntityRepository<EverWorksOutboundChange> {}

@Injectable()
export class MikroOrmEverWorksSyncLogRepository extends MikroOrmBaseEntityRepository<EverWorksSyncLog> {}
