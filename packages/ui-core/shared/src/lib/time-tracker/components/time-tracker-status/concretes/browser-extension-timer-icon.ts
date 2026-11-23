import { faBox } from '@fortawesome/free-solid-svg-icons';
import { TimeLogSourceEnum } from '@irtranscripts/contracts';
import { TimerIcon } from '@irtranscripts/ui-core/core';

export class BrowserExtensionTimerIcon extends TimerIcon {
	constructor() {
		super();
		this.source = TimeLogSourceEnum.BROWSER_EXTENSION;
		this.name = faBox;
	}
}
