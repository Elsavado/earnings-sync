import { IRTranscriptsCorePlugin as Plugin } from '@irtranscripts/plugin';
import { BaseAiProviderPlugin } from '@irtranscripts/plugin-ai-chat';
import { openRouterProviderDefinition } from './ai-provider-openrouter.provider';

/**
 * AiProviderOpenRouterPlugin
 *
 * Contributes the OpenRouter provider to the AI chat engine
 * (`@irtranscripts/plugin-ai-chat`) by registering {@link openRouterProviderDefinition}
 * with the provider registry on bootstrap (see {@link BaseAiProviderPlugin}).
 */
@Plugin({})
export class AiProviderOpenRouterPlugin extends BaseAiProviderPlugin {
	protected readonly definition = openRouterProviderDefinition;
}
