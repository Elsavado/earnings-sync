import { IAppIntegrationConfig } from '@irtranscripts/common';
import { ITermsAcceptanceClaim, IUserSigninWorkspaceResponse, LanguagesEnum } from '@irtranscripts/contracts';

/** The registration input this plugin passes to IRTranscripts's own register path. */
export interface ZitadelRegistrationInput {
	user: { email: string; firstName?: string; lastName?: string };
	terms?: ITermsAcceptanceClaim[];
}

/**
 * The parts of IRTranscripts's authentication service the plugin uses. Provided by the core authentication
 * service itself, so the e-mail code, its rate limits and the register path are IRTranscripts's own.
 */
export interface IRTranscriptsAuthPort {
	/** Sends IRTranscripts's one-time e-mail code to every active user with this e-mail. */
	sendWorkspaceSigninCode(input: { email: string } & Partial<IAppIntegrationConfig>, locale: LanguagesEnum): Promise<void>;

	/** Checks IRTranscripts's one-time e-mail code (and consumes it) and returns the workspaces it proved. */
	signinWorkspacesByMagicCode(
		payload: { email: string; code: string },
		includeTeams: boolean
	): Promise<IUserSigninWorkspaceResponse>;

	/** IRTranscripts's register path (the one `POST /api/auth/register` runs). */
	register(input: ZitadelRegistrationInput, languageCode: LanguagesEnum): Promise<{ id: string; tenantId?: string | null }>;
}

/** Injection token of {@link IRTranscriptsAuthPort}. */
export const IRTRANSCRIPTS_AUTH = 'AUTH_ZITADEL_IRTRANSCRIPTS_AUTH';
