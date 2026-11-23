import { IRTranscriptsCorePlugin as Plugin } from '@irtranscripts/plugin';
import { BaseAiProviderPlugin } from '@irtranscripts/plugin-ai-chat';
import { openAiProviderDefinition } from './ai-provider-openai.provider';

/**
 * AiProviderOpenAiPlugin
 *
 * Contributes the OpenAI provider to the AI chat engine
 * (`@irtranscripts/plugin-ai-chat`) by registering {@link openAiProviderDefinition}
 * with the provider registry on bootstrap (see {@link BaseAiProviderPlugin}).
 */
@Plugin({})
export class AiProviderOpenAiPlugin extends BaseAiProviderPlugin {
	protected readonly definition = openAiProviderDefinition;
}
