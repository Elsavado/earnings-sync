import { registerAs } from '@nestjs/config';

/**
 * IRTranscripts AI Configuration
 */
export default registerAs('irtranscriptsAI', () => ({
	irtranscriptsAIGraphQLEndpoint: process.env.IRTRANSCRIPTS_AI_GRAPHQL_ENDPOINT || null, // GraphQL endpoint for IRTranscripts AI
	irtranscriptsAIRESTEndpoint: process.env.IRTRANSCRIPTS_AI_REST_ENDPOINT || null, // REST endpoint for IRTranscripts AI
	irtranscriptsAIRequestTimeout: parseInt(process.env.IRTRANSCRIPTS_AI_REQUEST_TIMEOUT) || 60 * 5 * 1000, // Request timeout for IRTranscripts AI in milliseconds
	irtranscriptsAiApiKey: process.env.IRTRANSCRIPTS_AI_API_KEY || null, // IRTranscripts AI API key
	irtranscriptsAiApiSecret: process.env.IRTRANSCRIPTS_AI_API_SECRET || null // IRTranscripts AI API secret
}));
