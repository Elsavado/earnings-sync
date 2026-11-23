import { faMobile } from '@fortawesome/free-solid-svg-icons';
import { TimeLogSourceEnum } from '@irtranscripts/contracts';
import { TimerIcon } from '@irtranscripts/ui-core/core';

export class MobileTimerIcon extends TimerIcon {
	constructor() {
		super();
		this.source = TimeLogSourceEnum.MOBILE;
		this.name = faMobile;
	}
}
