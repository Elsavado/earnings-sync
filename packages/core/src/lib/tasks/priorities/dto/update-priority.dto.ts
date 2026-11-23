import { ITaskPriorityUpdateInput } from '@irtranscripts/contracts';
import { IntersectionType, PartialType } from '@nestjs/swagger';
import { TaskPriority } from '../priority.entity';
import { TenantOrganizationBaseDTO } from './../../../core/dto';

export class UpdateTaskPriorityDTO extends IntersectionType(
    PartialType(TenantOrganizationBaseDTO),
    PartialType(TaskPriority)
) implements ITaskPriorityUpdateInput { }
