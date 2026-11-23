import { OmitType, PartialType } from '@nestjs/swagger';
import { ICommentUpdateInput } from '@irtranscripts/contracts';
import { CreateCommentDTO } from './create-comment.dto';

/**
 * Update Comment data validation request DTO
 */
export class UpdateCommentDTO
	extends PartialType(OmitType(CreateCommentDTO, ['entity', 'entityId']))
	implements ICommentUpdateInput {}
