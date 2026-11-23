import { MikroOrmBaseEntityRepository } from '@irtranscripts/core';
import { Video } from '../entities/video.entity';

export class MikroOrmVideoRepository extends MikroOrmBaseEntityRepository<Video> {}
