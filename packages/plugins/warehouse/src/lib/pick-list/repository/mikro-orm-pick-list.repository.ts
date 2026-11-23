import { Injectable } from '@nestjs/common';
import { MikroOrmBaseEntityRepository } from '@irtranscripts/core';
import { PickList } from '../pick-list.entity';

@Injectable()
export class MikroOrmPickListRepository extends MikroOrmBaseEntityRepository<PickList> {}
