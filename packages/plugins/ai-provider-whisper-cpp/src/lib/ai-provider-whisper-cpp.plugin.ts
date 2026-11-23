import { IRTranscriptsCorePlugin as Plugin } from '@irtranscripts/plugin';
import { BaseAiProviderPlugin } from '@irtranscripts/plugin-ai-chat';
import { whisperCppProviderDefinition } from './ai-provider-whisper-cpp.provider';

/**
 * AiProviderWhisperCppPlugin
 *
 * Contributes the whisper.cpp provider to the AI chat engine
 * (`@irtranscripts/plugin-ai-chat`) by registering {@link whisperCppProviderDefinition}
 * with the provider registry on bootstrap (see {@link BaseAiProviderPlugin}).
 */
@Plugin({})
export class AiProviderWhisperCppPlugin extends BaseAiProviderPlugin {
	protected readonly definition = whisperCppProviderDefinition;
}
