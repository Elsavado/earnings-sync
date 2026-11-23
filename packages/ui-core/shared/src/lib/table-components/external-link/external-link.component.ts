import { Component, Input, ChangeDetectionStrategy } from '@angular/core';

@Component({
    selector: 'irtranscripts-external-link',
    templateUrl: './external-link.component.html',
    styleUrls: ['./external-link.component.scss'],
    changeDetection: ChangeDetectionStrategy.Eager,
    standalone: false
})
export class ExternalLinkComponent {
	@Input()
	value: string;

	@Input()
	rowData: any;

	constructor() { }
}
