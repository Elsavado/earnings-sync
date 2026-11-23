import { IntersectionType } from '@nestjs/swagger';
import { TenantOrganizationBaseDTO } from '@irtranscripts/core';
import { IMatchingCriterions } from '@irtranscripts/contracts';

export class SaveJobPresetCriterionDTO
	extends IntersectionType(TenantOrganizationBaseDTO)
	implements IMatchingCriterions {}
