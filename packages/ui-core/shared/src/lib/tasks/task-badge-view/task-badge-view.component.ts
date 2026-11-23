import { Component, Input, ChangeDetectionStrategy } from '@angular/core';
import { ColorAdapter } from '@irtranscripts/ui-core/core';
import { ITaskPriority, ITaskSize, ITaskStatus } from '@irtranscripts/contracts';

export type ITaskBadge = ITaskStatus | ITaskSize | ITaskPriority;

@Component({
    selector: 'irtranscripts-task-badge-view',
    templateUrl: './task-badge-view.component.html',
    styleUrls: ['./task-badge-view.component.scss'],
    changeDetection: ChangeDetectionStrategy.Eager,
    standalone: false
})
export class TaskBadgeViewComponent {
	private _taskBadge: ITaskBadge = null;
	public get taskBadge(): ITaskBadge {
		return this._taskBadge;
	}
	@Input() public set taskBadge(value: ITaskBadge) {
		this._taskBadge = value;
	}

	public get textColor() {
		return ColorAdapter.contrast(this.taskBadge.color);
	}

	public get backgroundColor() {
		return ColorAdapter.background(this.taskBadge.color);
	}

	public get icon() {
		return this.taskBadge.fullIconUrl;
	}

	public get name() {
		return this.taskBadge.name;
	}

	public get imageFilter() {
		return ColorAdapter.hexToHsl(this.taskBadge.color);
	}
}
