import { IntersectionType, PartialType } from "@nestjs/mapped-types";
import { IProposalCreateInput } from "@irtranscripts/contracts";
import { EmployeeFeatureDTO, RelationalTagDTO } from "@irtranscripts/core";
import { ProposalDTO } from "./proposal.dto";

/**
 * Create proposal request DTO validation
 */
export class CreateProposalDTO extends IntersectionType(
    ProposalDTO,
    PartialType(EmployeeFeatureDTO),
    RelationalTagDTO
) implements IProposalCreateInput { }
