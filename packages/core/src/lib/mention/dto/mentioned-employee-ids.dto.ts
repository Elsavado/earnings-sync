import { ApiPropertyOptional } from '@nestjs/swagger';
import { IsArray, IsOptional } from 'class-validator';
import { ID, IMentionEmployeeIds } from '@irtranscripts/contracts';

export class MentionEmployeeIdsDTO implements IMentionEmployeeIds {
	@ApiPropertyOptional({ type: () => Array })
	@IsOptional()
	@IsArray()
	mentionEmployeeIds?: ID[];
}
