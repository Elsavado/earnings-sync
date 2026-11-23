import { IRTranscriptsCorePlugin as Plugin } from '@irtranscripts/plugin';
import { BaseAiProviderPlugin } from '@irtranscripts/plugin-ai-chat';
import { geminiProviderDefinition } from './ai-provider-gemini.provider';

/**
 * AiProviderGeminiPlugin
 *
 * Contributes the Gemini provider to the AI chat engine
 * (`@irtranscripts/plugin-ai-chat`) by registering {@link geminiProviderDefinition}
 * with the provider registry on bootstrap (see {@link BaseAiProviderPlugin}).
 */
@Plugin({})
export class AiProviderGeminiPlugin extends BaseAiProviderPlugin {
	protected readonly definition = geminiProviderDefinition;
}
