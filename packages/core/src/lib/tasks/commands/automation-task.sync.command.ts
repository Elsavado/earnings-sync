import { IIntegrationMapSyncEntity, ITaskCreateInput, ITaskUpdateInput, IntegrationEntity } from '@irtranscripts/contracts';

export class AutomationTaskSyncCommand {
	constructor(
		public readonly input: IIntegrationMapSyncEntity<ITaskCreateInput | ITaskUpdateInput>,
		public readonly entity: IntegrationEntity
	) {}
}
