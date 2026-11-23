import { IconDefinition } from '@fortawesome/free-solid-svg-icons';
import { TimeLogSourceEnum } from '@irtranscripts/contracts';

export interface ITimerIcon {
	source: TimeLogSourceEnum;
	name: IconDefinition;
}
