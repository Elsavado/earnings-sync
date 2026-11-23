module.exports = {
	displayName: 'plugin-ai-provider-groq',
	preset: '../../../jest.preset.js',
	testEnvironment: 'node',
	transform: {
		'^.+\\.[tj]s$': ['ts-jest', { tsconfig: '<rootDir>/tsconfig.spec.json' }]
	},
	// Provider specs map the `@irtranscripts/plugin-ai-chat` barrel (which drags in the NestJS plugin and
	// @irtranscripts/core) onto its helpers-only entry point — real catalogue cache/fetch and real speech
	// request, minus the entity graph. Anything else (`BaseAiProviderPlugin`, `importEsm`,
	// `AiProviderRegistry`) is `undefined` under this mapping; no spec here calls `createModel`.
	moduleNameMapper: {
		'^@irtranscripts/plugin-ai-chat$': '<rootDir>/../ai-chat/src/lib/provider-helpers.ts'
	},
	moduleFileExtensions: ['ts', 'js', 'html'],
	coverageDirectory: '../../../coverage/packages/plugins/ai-provider-groq'
};
