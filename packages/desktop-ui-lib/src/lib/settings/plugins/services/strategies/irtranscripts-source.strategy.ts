import { IIRTranscriptsSource, IPluginSource } from '@irtranscripts/contracts';
import { ISourceStrategy } from '../../shared/plugin.model';

export class IRTranscriptsSourceStrategy implements ISourceStrategy<IIRTranscriptsSource> {
	public appendToFormData(formData: FormData, source: IIRTranscriptsSource): void {
		if (!source.file || !(source.file instanceof File)) {
			throw new Error('File is required for IRTranscripts Source.');
		}
		formData.append('file', source.file);
	}

	public getSourceData(source: IIRTranscriptsSource): Partial<IPluginSource> {
		return {
			fileName: source.file.name
		};
	}
}
