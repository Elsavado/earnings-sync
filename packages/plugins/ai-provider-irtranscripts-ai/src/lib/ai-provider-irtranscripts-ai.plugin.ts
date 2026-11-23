import { IRTranscriptsCorePlugin as Plugin } from '@irtranscripts/plugin';
import { BaseAiProviderPlugin } from '@irtranscripts/plugin-ai-chat';
import { irtranscriptsAiProviderDefinition } from './ai-provider-irtranscripts-ai.provider';

/**
 * AiProviderIRTranscriptsAiPlugin
 *
 * Contributes the IRTranscripts AI (placeholder — chat not routed yet) provider to the AI chat engine
 * (`@irtranscripts/plugin-ai-chat`) by registering {@link irtranscriptsAiProviderDefinition}
 * with the provider registry on bootstrap (see {@link BaseAiProviderPlugin}).
 */
@Plugin({})
export class AiProviderIRTranscriptsAiPlugin extends BaseAiProviderPlugin {
	protected readonly definition = irtranscriptsAiProviderDefinition;
}
