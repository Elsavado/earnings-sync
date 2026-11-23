import { IntersectionType } from '@nestjs/swagger';
import { IGetTimeSlotInput } from '@irtranscripts/contracts';
import { FiltersQueryDTO, RelationsQueryDTO, SelectorsQueryDTO } from '../../../shared/dto';

/**
 * Get time slot request DTO validation
 */
export class TimeSlotQueryDTO
	extends IntersectionType(FiltersQueryDTO, RelationsQueryDTO, SelectorsQueryDTO)
	implements IGetTimeSlotInput {}
