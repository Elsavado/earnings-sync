import { IRTranscriptsCorePlugin as Plugin } from '@irtranscripts/plugin';
import { BaseAiProviderPlugin } from '@irtranscripts/plugin-ai-chat';
import { groqProviderDefinition } from './ai-provider-groq.provider';

/**
 * AiProviderGroqPlugin
 *
 * Contributes the Groq provider to the AI chat engine
 * (`@irtranscripts/plugin-ai-chat`) by registering {@link groqProviderDefinition}
 * with the provider registry on bootstrap (see {@link BaseAiProviderPlugin}).
 */
@Plugin({})
export class AiProviderGroqPlugin extends BaseAiProviderPlugin {
	protected readonly definition = groqProviderDefinition;
}
