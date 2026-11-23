import { PartialType } from '@nestjs/swagger';
import { IOfficialHolidayUpdateInput } from '@irtranscripts/contracts';
import { CreateOfficialHolidayDTO } from './create-official-holiday.dto';

/**
 * Update Official Holiday request DTO.
 */
export class UpdateOfficialHolidayDTO
	extends PartialType(CreateOfficialHolidayDTO)
	implements IOfficialHolidayUpdateInput {}
