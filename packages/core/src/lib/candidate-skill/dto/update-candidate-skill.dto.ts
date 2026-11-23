import { ICandidateSkillUpdateInput } from "@irtranscripts/contracts";
import { ApiProperty } from "@nestjs/swagger";
import { IsNotEmpty, IsString } from "class-validator";
import { TenantOrganizationBaseDTO } from "./../../core/dto";

export class UpdateCandidateSkillDTO extends TenantOrganizationBaseDTO  implements ICandidateSkillUpdateInput {

    @ApiProperty({ type: () => String, required: true, readOnly: true })
    @IsNotEmpty()
    @IsString()
    readonly name: string;
}