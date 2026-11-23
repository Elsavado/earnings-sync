import { PartialType } from '@nestjs/swagger';
import { ITagTypeUpdateInput } from '@irtranscripts/contracts';
import { CreateTagTypeDTO } from './create-tag-type.dto';

/**
 * DTO for updating a Tag Type
 */
export class UpdateTagTypeDTO
    extends PartialType(CreateTagTypeDTO)
        implements ITagTypeUpdateInput {}
