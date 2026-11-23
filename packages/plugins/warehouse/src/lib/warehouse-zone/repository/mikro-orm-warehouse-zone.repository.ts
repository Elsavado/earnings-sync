import { Injectable } from '@nestjs/common';
import { MikroOrmBaseEntityRepository } from '@irtranscripts/core';
import { WarehouseZone } from '../warehouse-zone.entity';

@Injectable()
export class MikroOrmWarehouseZoneRepository extends MikroOrmBaseEntityRepository<WarehouseZone> {}
