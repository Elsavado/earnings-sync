import { ITimeLog, TimeLogSourceEnum } from '@irtranscripts/contracts';

export interface IRemoteTimer {
	source: TimeLogSourceEnum;
	running: boolean;
	startedAt: Date;
	stoppedAt: Date;
	lastLog: ITimeLog;
	isExternalSource: boolean;
}
