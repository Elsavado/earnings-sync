import { ITaskCreateInput } from '@irtranscripts/contracts';
import { IntersectionType, OmitType } from '@nestjs/swagger';
import { TenantOrganizationBaseDTO } from './../../core/dto';
import { MentionEmployeeIdsDTO } from '../../mention/dto';
import { Task } from './../task.entity';

/**
 * Create task validation request DTO
 */
export class CreateTaskDTO
	extends IntersectionType(
		TenantOrganizationBaseDTO,
		IntersectionType(OmitType(Task, ['organizationId', 'organization']), MentionEmployeeIdsDTO)
	)
	implements ITaskCreateInput {}
