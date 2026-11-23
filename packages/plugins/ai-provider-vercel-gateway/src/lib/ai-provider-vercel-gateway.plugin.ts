import { IRTranscriptsCorePlugin as Plugin } from '@irtranscripts/plugin';
import { BaseAiProviderPlugin } from '@irtranscripts/plugin-ai-chat';
import { vercelGatewayProviderDefinition } from './ai-provider-vercel-gateway.provider';

/**
 * AiProviderVercelGatewayPlugin
 *
 * Contributes the Vercel AI Gateway provider to the AI chat engine
 * (`@irtranscripts/plugin-ai-chat`) by registering {@link vercelGatewayProviderDefinition}
 * with the provider registry on bootstrap (see {@link BaseAiProviderPlugin}).
 */
@Plugin({})
export class AiProviderVercelGatewayPlugin extends BaseAiProviderPlugin {
	protected readonly definition = vercelGatewayProviderDefinition;
}
