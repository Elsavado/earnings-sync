import { faArrowsTurnToDots } from '@fortawesome/free-solid-svg-icons';
import { TimeLogSourceEnum } from '@irtranscripts/contracts';
import { TimerIcon } from '../interfaces';

export class HubstaffTimerIcon extends TimerIcon {
	constructor() {
		super();
		this.source = TimeLogSourceEnum.HUBSTAFF;
		this.name = faArrowsTurnToDots;
	}
}
