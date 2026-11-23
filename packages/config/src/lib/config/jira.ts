import { registerAs } from '@nestjs/config';
import { IJiraIntegrationConfig } from '@irtranscripts/common';

/**
 * Register Jira configuration using @nestjs/config
 */
export default registerAs(
	'jira',
	(): IJiraIntegrationConfig => ({
		appName: process.env.IRTRANSCRIPTS_JIRA_APP_NAME,
		appDescription: process.env.IRTRANSCRIPTS_JIRA_APP_DESCRIPTION,
		appKey: process.env.IRTRANSCRIPTS_JIRA_APP_KEY,
		baseUrl: process.env.IRTRANSCRIPTS_JIRA_APP_BASE_URL,
		vendorName: process.env.IRTRANSCRIPTS_JIRA_APP_BASE_VENDOR_NAME,
		vendorUrl: process.env.IRTRANSCRIPTS_JIRA_APP_BASE_VENDOR_URL
	})
);
