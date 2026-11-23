import { ApiProperty } from '@nestjs/swagger';
import { IsEmail, IsNotEmpty } from 'class-validator';
import { IUserEmailInput } from '@irtranscripts/contracts';

/**
 * User email input DTO validation
 */
export class UserEmailDTO implements IUserEmailInput {
	@ApiProperty({ type: () => String })
	@IsNotEmpty()
	@IsEmail()
	readonly email: string;
}
