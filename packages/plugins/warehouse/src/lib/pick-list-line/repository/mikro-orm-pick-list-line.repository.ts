import { Injectable } from '@nestjs/common';
import { MikroOrmBaseEntityRepository } from '@irtranscripts/core';
import { PickListLine } from '../pick-list-line.entity';

@Injectable()
export class MikroOrmPickListLineRepository extends MikroOrmBaseEntityRepository<PickListLine> {}
