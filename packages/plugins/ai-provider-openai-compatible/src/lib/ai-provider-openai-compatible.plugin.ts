import { IRTranscriptsCorePlugin as Plugin } from '@irtranscripts/plugin';
import { BaseAiProviderPlugin } from '@irtranscripts/plugin-ai-chat';
import { openAiCompatibleProviderDefinition } from './ai-provider-openai-compatible.provider';

/**
 * AiProviderOpenAiCompatiblePlugin
 *
 * Contributes the OpenAI-compatible provider to the AI chat engine
 * (`@irtranscripts/plugin-ai-chat`) by registering {@link openAiCompatibleProviderDefinition}
 * with the provider registry on bootstrap (see {@link BaseAiProviderPlugin}).
 */
@Plugin({})
export class AiProviderOpenAiCompatiblePlugin extends BaseAiProviderPlugin {
	protected readonly definition = openAiCompatibleProviderDefinition;
}
