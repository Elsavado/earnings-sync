import { IRTranscriptsCorePlugin as Plugin } from '@irtranscripts/plugin';
import { BaseAiProviderPlugin } from '@irtranscripts/plugin-ai-chat';
import { localAiProviderDefinition } from './ai-provider-localai.provider';

/**
 * AiProviderLocalAiPlugin
 *
 * Contributes the LocalAI provider to the AI chat engine
 * (`@irtranscripts/plugin-ai-chat`) by registering {@link localAiProviderDefinition}
 * with the provider registry on bootstrap (see {@link BaseAiProviderPlugin}).
 */
@Plugin({})
export class AiProviderLocalAiPlugin extends BaseAiProviderPlugin {
	protected readonly definition = localAiProviderDefinition;
}
