const baseConfig = require('../../../eslint.config.js');

/**
 * The instance identity holds a private key and makes no outbound request: it may not import an HTTP
 * client, nor any analytics plugin.
 */
module.exports = [
	...baseConfig,
	{
		files: ['**/*.ts'],
		rules: {
			'no-restricted-imports': [
				'error',
				{
					paths: [
						{ name: '@irtranscripts/plugin-jitsu-analytics', message: 'The instance identity never uses analytics plugins.' },
						{ name: '@irtranscripts/plugin-posthog', message: 'The instance identity never uses analytics plugins.' },
						{ name: '@irtranscripts/plugin-ever-connect', message: 'The instance identity is shared; it does not depend on a module that uses it.' },
						{ name: '@nestjs/axios', message: 'The instance identity makes no outbound request.' },
						{ name: 'axios', message: 'The instance identity makes no outbound request.' },
						{ name: 'undici', message: 'The instance identity makes no outbound request.' }
					]
				}
			]
		}
	}
];
