import { faUsers } from '@fortawesome/free-solid-svg-icons';
import { TimeLogSourceEnum } from '@irtranscripts/contracts';
import { TimerIcon } from '../interfaces';

export class TeamTimerIcon extends TimerIcon {
	constructor() {
		super();
		this.source = TimeLogSourceEnum.TEAMS;
		this.name = faUsers;
	}
}
