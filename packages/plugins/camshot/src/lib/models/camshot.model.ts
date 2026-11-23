import {
	FileStorageProviderEnum,
	IBasePerTenantAndOrganizationEntityModel,
	ICamshot as ICamshotContract,
	ID,
	IRelationalUser,
	ITimeSlot
} from "@irtranscripts/contracts";

export interface ICamshot extends ICamshotContract,
	IBasePerTenantAndOrganizationEntityModel,
	IRelationalUser {
	fileKey?: string;
	thumbKey?: string;
	timeSlotId?: ID;
	timeSlot?: ITimeSlot;
	storageProvider: FileStorageProviderEnum;
}
