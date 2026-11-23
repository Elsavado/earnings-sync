import { CurrenciesEnum, DefaultValueDateTypeEnum } from '@irtranscripts/contracts';

export const DEFAULT_EVER_ORGANIZATIONS = [
	{
		name: 'Ever Technologies LTD',
		currency: CurrenciesEnum.BGN,
		defaultValueDateType: DefaultValueDateTypeEnum.TODAY,
		imageUrl: 'assets/images/logos/ever-large.jpg',
		isDefault: true,
		totalEmployees: 17
	},
	{
		name: 'Ever Co. Ltd',
		currency: CurrenciesEnum.ILS,
		defaultValueDateType: DefaultValueDateTypeEnum.TODAY,
		imageUrl: 'assets/images/logos/ever-large.jpg',
		isDefault: false,
		totalEmployees: 0
	}
];

export const DEFAULT_ORGANIZATIONS = [
	{
		name: 'Default Company',
		currency: CurrenciesEnum.USD,
		defaultValueDateType: DefaultValueDateTypeEnum.TODAY,
		imageUrl: 'assets/images/logos/logo_IRTranscripts.svg',
		isDefault: true,
		totalEmployees: 1
	}
];
