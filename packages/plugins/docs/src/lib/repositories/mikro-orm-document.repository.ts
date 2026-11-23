import { MikroOrmBaseEntityRepository } from '@irtranscripts/core';
import { Document } from '../entities/document.entity';

export class MikroOrmDocumentRepository extends MikroOrmBaseEntityRepository<Document> {}
