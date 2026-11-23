import { IRTranscriptsCorePlugin as Plugin } from '@irtranscripts/plugin';
import { BaseAiProviderPlugin } from '@irtranscripts/plugin-ai-chat';
import { speachesProviderDefinition } from './ai-provider-speaches.provider';

/**
 * AiProviderSpeachesPlugin
 *
 * Contributes the Speaches provider to the AI chat engine
 * (`@irtranscripts/plugin-ai-chat`) by registering {@link speachesProviderDefinition}
 * with the provider registry on bootstrap (see {@link BaseAiProviderPlugin}).
 */
@Plugin({})
export class AiProviderSpeachesPlugin extends BaseAiProviderPlugin {
	protected readonly definition = speachesProviderDefinition;
}
