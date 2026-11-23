import { MikroOrmBaseEntityRepository } from '@irtranscripts/core';
import { PluginVersion } from '../entities/plugin-version.entity';

export class MikroOrmPluginVersionRepository extends MikroOrmBaseEntityRepository<PluginVersion> {}
