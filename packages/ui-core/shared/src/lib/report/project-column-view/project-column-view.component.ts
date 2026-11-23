import { Component, Input, ChangeDetectionStrategy } from '@angular/core';
import { IOrganizationProject } from '@irtranscripts/contracts';
import { DEFAULT_SVG } from '@irtranscripts/ui-core/common';

@Component({
    selector: 'ga-project-column-view',
    templateUrl: './project-column-view.component.html',
    styleUrls: ['./project-column-view.component.scss'],
    changeDetection: ChangeDetectionStrategy.Eager,
    standalone: false
})
export class ProjectColumnViewComponent {
	fallbackSvg = DEFAULT_SVG;

	@Input() project: IOrganizationProject;

	constructor() {}
}
