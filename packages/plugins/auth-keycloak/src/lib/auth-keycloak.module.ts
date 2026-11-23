import { Module } from '@nestjs/common';
import { OidcModule } from '@irtranscripts/auth';
import { AuthModule, AuthService } from '@irtranscripts/core';
import { AuthKeycloakController } from './auth-keycloak.controller';
import { KeycloakAuthGuard } from './keycloak-auth-guard';
import { KeycloakSignInService } from './keycloak-sign-in.service';
import { KeycloakStrategy } from './keycloak.strategy';
import { SOCIAL_SIGN_IN } from './social-sign-in.port';

/**
 * Registers the Keycloak passport strategy and guard (moved here unchanged from `@irtranscripts/auth`) and the
 * Keycloak sign-in routes.
 */
@Module({
	imports: [OidcModule, AuthModule],
	controllers: [AuthKeycloakController],
	providers: [
		KeycloakStrategy,
		KeycloakAuthGuard,
		KeycloakSignInService,
		// IRTranscripts's existing social sign-in (link by verified e-mail), as the other social routes use it.
		{ provide: SOCIAL_SIGN_IN, useExisting: AuthService }
	],
	exports: [KeycloakAuthGuard]
})
export class AuthKeycloakModule {}
