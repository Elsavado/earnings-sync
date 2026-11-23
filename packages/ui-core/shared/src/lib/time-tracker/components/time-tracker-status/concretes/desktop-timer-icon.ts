import { faDesktop } from '@fortawesome/free-solid-svg-icons';
import { TimeLogSourceEnum } from '@irtranscripts/contracts';
import { TimerIcon } from '@irtranscripts/ui-core/core';

export class DesktopTimerIcon extends TimerIcon {
	constructor() {
		super();
		this.source = TimeLogSourceEnum.DESKTOP;
		this.name = faDesktop;
	}
}
