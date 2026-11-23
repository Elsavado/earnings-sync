import { ITaskEstimationUpdateInput } from '@irtranscripts/contracts';
import { CreateTaskEstimationDTO } from './create-task-estimation.dto';

/**
 * Update task estimation validation request DTO
 */
export class UpdateTaskEstimationDTO
	extends CreateTaskEstimationDTO
	implements ITaskEstimationUpdateInput {}
