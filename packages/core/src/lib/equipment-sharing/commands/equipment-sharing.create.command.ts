import { ICommand } from '@nestjs/cqrs';
import { ID, IEquipmentSharingCreateInput } from '@irtranscripts/contracts';

export class EquipmentSharingCreateCommand implements ICommand {
	static readonly type = '[EquipmentSharing] Create';

	constructor(public readonly organizationId: ID, public readonly input: IEquipmentSharingCreateInput) {}
}
