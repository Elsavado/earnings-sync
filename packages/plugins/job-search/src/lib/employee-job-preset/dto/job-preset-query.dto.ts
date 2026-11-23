import { IntersectionType, PartialType, PickType } from '@nestjs/swagger';
import { IGetJobPresetInput } from '@irtranscripts/contracts';
import { EmployeeFeatureDTO, TenantOrganizationBaseDTO } from '@irtranscripts/core';

export class JobPresetQueryDTO extends IntersectionType(
	TenantOrganizationBaseDTO,
	PartialType(PickType(EmployeeFeatureDTO, ['employeeId']))
) implements IGetJobPresetInput { }
