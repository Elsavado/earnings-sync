import { IntersectionType, OmitType } from "@nestjs/swagger";
import { ISharedEntityUpdateInput } from "@irtranscripts/contracts";
import { TenantOrganizationBaseDTO } from "../../core/dto";
import { SharedEntity } from "../shared-entity.entity";

/**
 * Update Shared Entity DTO
 */
export class UpdateSharedEntityDTO extends IntersectionType(TenantOrganizationBaseDTO, OmitType(SharedEntity, ['token', 'entity', 'entityId'])) implements ISharedEntityUpdateInput {}
