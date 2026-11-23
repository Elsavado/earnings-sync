import { ChangeDetectionStrategy, Component, Inject } from '@angular/core';
import { DomSanitizer, SafeResourceUrl } from '@angular/platform-browser';
import { IRTRANSCRIPTS_ENV } from '../../../../constants';

@Component({
	selector: 'irtranscripts-logo',
	templateUrl: './logo.component.html',
	styleUrls: ['./logo.component.scss'],
	changeDetection: ChangeDetectionStrategy.OnPush
})
export class LogoComponent {
	constructor(
		private readonly _domSanitizer: DomSanitizer,
		@Inject(IRTRANSCRIPTS_ENV)
		private readonly _environment: any
	) {}

	public get logoUrl(): SafeResourceUrl {
		return this._domSanitizer.bypassSecurityTrustResourceUrl(this._environment.PLATFORM_LOGO);
	}
}
