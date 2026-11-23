import { FormControl, FormGroup, Validators } from '@angular/forms';
import { IIRTranscriptsSource, PluginSourceType } from '@irtranscripts/contracts';
import { SourceCreator } from '../source.creator';

export class IRTranscriptsSourceCreator extends SourceCreator {
	public createSource(source?: IIRTranscriptsSource): FormGroup {
		const base = this.createBaseSource(PluginSourceType.IRTRANSCRIPTS, source);
		return new FormGroup({
			...base,
			file: new FormControl(source?.file || null, Validators.required)
		});
	}
}
