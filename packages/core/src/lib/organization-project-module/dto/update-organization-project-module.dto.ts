import { PartialType } from '@nestjs/swagger';
import { IOrganizationProjectModuleUpdateInput } from '@irtranscripts/contracts';
import { WithoutInitializers } from '@irtranscripts/common';
import { CreateOrganizationProjectModuleDTO } from './create-organization-project-module.dto';

/**
 * Update Organization Project Module validation request DTO.
 *
 * Built through `WithoutInitializers`: `MemberEntityBasedDTO` defaults `memberIds` and `managerIds` to empty lists, and
 * a `PUT` that did not name them reached the service as "replace the members with none" (review R3-04).
 */
export class UpdateOrganizationProjectModuleDTO
	extends WithoutInitializers(PartialType(CreateOrganizationProjectModuleDTO))
	implements IOrganizationProjectModuleUpdateInput {}
