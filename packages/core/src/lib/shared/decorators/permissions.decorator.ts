import { SetMetadata } from '@nestjs/common';
import { PERMISSIONS_METADATA } from '@irtranscripts/constants';
import { PermissionsEnum } from '@irtranscripts/contracts';

export const Permissions = (...permissions: PermissionsEnum[]) => SetMetadata(PERMISSIONS_METADATA, permissions);
