import { LegacyFindManyOptions } from '@irtranscripts/core';
import { IQuery } from '@nestjs/cqrs';
import { PluginCategory } from '../../../domain';

export class GetPluginCategoriesQuery implements IQuery {
	static readonly type = '[Plugin Category] Get Categories';

	constructor(public readonly options?: LegacyFindManyOptions<PluginCategory>) {}
}
