import { ICommand } from '@nestjs/cqrs';
import { ID, IEquipmentSharingUpdateInput } from '@irtranscripts/contracts';

export class EquipmentSharingUpdateCommand implements ICommand {
	static readonly type = '[EquipmentSharing] Update';

	constructor(public readonly id: ID, public readonly input: IEquipmentSharingUpdateInput) {}
}
