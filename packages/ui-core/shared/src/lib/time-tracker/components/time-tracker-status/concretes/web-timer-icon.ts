import { faGlobe } from '@fortawesome/free-solid-svg-icons';
import { TimeLogSourceEnum } from '@irtranscripts/contracts';
import { TimerIcon } from '@irtranscripts/ui-core/core';

export class WebTimerIcon extends TimerIcon {
	constructor() {
		super();
		this.source = TimeLogSourceEnum.WEB_TIMER;
		this.name = faGlobe;
	}
}
