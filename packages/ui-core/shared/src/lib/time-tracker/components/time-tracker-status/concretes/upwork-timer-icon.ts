import { faArrowTurnUp } from '@fortawesome/free-solid-svg-icons';
import { TimeLogSourceEnum } from '@irtranscripts/contracts';
import { TimerIcon } from '@irtranscripts/ui-core/core';

export class UpworkTimerIcon extends TimerIcon {
	constructor() {
		super();
		this.source = TimeLogSourceEnum.UPWORK;
		this.name = faArrowTurnUp;
	}
}
