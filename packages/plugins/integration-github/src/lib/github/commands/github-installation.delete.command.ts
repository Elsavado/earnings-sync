import { IntegrationTenant } from '@irtranscripts/core';

export class GithubInstallationDeleteCommand {
	constructor(public readonly integration: IntegrationTenant) {}
}
