import { IProxyConfig, ISsl } from '@irtranscripts/contracts';

export interface ISslFactory {
	createSslConfig(config: IProxyConfig): ISsl;
}
