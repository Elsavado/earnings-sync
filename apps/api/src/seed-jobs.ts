import { seedJob } from '@irtranscripts/core';
import { pluginConfig } from './plugin.config';

seedJob(pluginConfig).catch((error: any) => {
	console.log(error);
	process.exit(1);
});
