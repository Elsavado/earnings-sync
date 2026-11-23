import { IntersectionType, PartialType } from '@nestjs/swagger';
import { ITaskStatusUpdateInput } from '@irtranscripts/contracts';
import { TenantOrganizationBaseDTO } from './../../../core/dto';
import { TaskStatus } from '../status.entity';

export class UpdatesStatusDTO
	extends IntersectionType(PartialType(TenantOrganizationBaseDTO), PartialType(TaskStatus))
	implements ITaskStatusUpdateInput {}
