import { ConfigModule, ConfigService } from '@nestjs/config';
import { HttpModule } from '@nestjs/axios';
import { DynamicModule, Module } from '@nestjs/common';
import { IRTRANSCRIPTS_AI_CONFIG_TOKEN } from '@irtranscripts/constants';
import { IRTranscriptsAIService } from './irtranscripts-ai.service';
import irtranscriptsAI from './config/irtranscripts-ai';
import { IConfigurationOptions } from './configuration.interface';
import { RequestConfigProvider } from './request-config.provider';

@Module({
	imports: [
		HttpModule.registerAsync({
			imports: [ConfigModule],
			useFactory: (config: ConfigService) => ({
				baseURL: config.get<string>('irtranscriptsAI.irtranscriptsAIRESTEndpoint'),
				timeout: config.get<number>('irtranscriptsAI.irtranscriptsAIRequestTimeout'),
				maxRedirects: 5,
				headers: {
					'Content-Type': 'application/json',
					apiKey: config.get<string>('irtranscriptsAI.irtranscriptsAiApiKey'),
					apiSecret: config.get<string>('irtranscriptsAI.irtranscriptsAiApiSecret')
				}
			}),
			inject: [ConfigService]
		}),
		ConfigModule.forFeature(irtranscriptsAI) // Make sure to import ConfigModule here
	],
	controllers: [],
	providers: [IRTranscriptsAIService, RequestConfigProvider],
	exports: [IRTranscriptsAIService, RequestConfigProvider]
})
export class IRTranscriptsAIModule {
	/**
	 * Configure the IRTranscriptsAI module for integration with Ever IRTranscripts Platform.
	 * @param options Optional configuration options for IRTranscriptsAI.
	 * @returns A dynamic module configuration object.
	 */
	static forRoot(options?: IConfigurationOptions): DynamicModule {
		return {
			module: IRTranscriptsAIModule,
			imports: [ConfigModule], // Make sure to import ConfigModule here
			providers: [
				{
					provide: IRTRANSCRIPTS_AI_CONFIG_TOKEN,
					useFactory: (config: ConfigService): IConfigurationOptions => ({
						apiKey: config.get<string>('irtranscriptsAI.irtranscriptsAiApiKey'),
						apiSecret: config.get<string>('irtranscriptsAI.irtranscriptsAiApiSecret'),
						...options
					}),
					inject: [ConfigService]
				}
			],
			exports: [IRTRANSCRIPTS_AI_CONFIG_TOKEN]
		};
	}
}
