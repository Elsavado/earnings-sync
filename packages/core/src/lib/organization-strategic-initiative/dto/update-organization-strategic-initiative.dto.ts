import { PartialType } from '@nestjs/swagger';
import { IOrganizationStrategicInitiativeUpdateInput } from '@irtranscripts/contracts';
import { CreateOrganizationStrategicInitiativeDTO } from './create-organization-strategic-initiative.dto';

/**
 * Update Organization Strategic Initiative data validation request DTO
 */
export class UpdateOrganizationStrategicInitiativeDTO
	extends PartialType(CreateOrganizationStrategicInitiativeDTO)
	implements IOrganizationStrategicInitiativeUpdateInput {}
