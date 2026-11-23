import { Component, Input, OnInit, ChangeDetectionStrategy } from '@angular/core';

@Component({
    selector: 'irtranscripts-description',
    templateUrl: './description.component.html',
    styleUrls: ['./description.component.css'],
    changeDetection: ChangeDetectionStrategy.Eager,
    standalone: false
})
export class DescriptionComponent implements OnInit {

	@Input() value: string | number;
	@Input() rowData: any;

	constructor() { }

	ngOnInit(): void {
	}
}
