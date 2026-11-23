import { MikroOrmBaseEntityRepository } from '@irtranscripts/core';
import { Plugin } from '../entities/plugin.entity';

export class MikroOrmPluginRepository extends MikroOrmBaseEntityRepository<Plugin> {}
