import { CustomDecorator, SetMetadata } from '@nestjs/common';
import { ROLES_METADATA } from '@irtranscripts/constants';
import { RolesEnum } from '@irtranscripts/contracts';

export const Roles = (...roles: RolesEnum[]): CustomDecorator => SetMetadata(ROLES_METADATA, roles);
