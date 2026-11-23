import { IRTranscriptsCorePlugin as Plugin } from '@irtranscripts/plugin';
import { BaseAiProviderPlugin } from '@irtranscripts/plugin-ai-chat';
import { elevenLabsProviderDefinition } from './ai-provider-elevenlabs.provider';

/**
 * AiProviderElevenLabsPlugin
 *
 * Contributes the ElevenLabs provider to the AI chat engine
 * (`@irtranscripts/plugin-ai-chat`) by registering {@link elevenLabsProviderDefinition}
 * with the provider registry on bootstrap (see {@link BaseAiProviderPlugin}).
 */
@Plugin({})
export class AiProviderElevenLabsPlugin extends BaseAiProviderPlugin {
	protected readonly definition = elevenLabsProviderDefinition;
}
