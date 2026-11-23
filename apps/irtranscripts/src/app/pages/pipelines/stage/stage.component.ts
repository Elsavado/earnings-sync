import { Component, OnInit, Input, ChangeDetectionStrategy } from '@angular/core';
import { IPipelineStage } from '@irtranscripts/contracts';

@Component({
    selector: 'irtranscripts-stage',
    templateUrl: './stage.component.html',
    styleUrls: ['./stage.component.scss'],
    changeDetection: ChangeDetectionStrategy.Eager,
    standalone: false
})
export class StageComponent implements OnInit {

	@Input() value: any;

	pipelineStages: IPipelineStage[];

	constructor() { }

	ngOnInit(): void {
		this.pipelineStages = this.value;
	}
}
