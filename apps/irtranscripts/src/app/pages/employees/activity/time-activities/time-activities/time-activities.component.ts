import { Component, OnInit, ViewChild, ChangeDetectionStrategy } from '@angular/core';
import { Observable } from 'rxjs';
import { ITimeLogFilters, ReportGroupByFilter, ReportGroupFilterEnum } from '@irtranscripts/contracts';
import { DateRangePickerBuilderService, TimesheetFilterService } from '@irtranscripts/ui-core/core';
import { IRTranscriptsFiltersComponent } from '@irtranscripts/ui-core/shared';

@Component({
	selector: 'irtranscripts-time-activities',
	templateUrl: './time-activities.component.html',
	styleUrls: ['./time-activities.component.scss'],
	changeDetection: ChangeDetectionStrategy.Eager,
	standalone: false
})
export class TimeActivitiesComponent implements OnInit {
	filters: ITimeLogFilters;
	datePickerConfig$: Observable<any> = this.dateRangePickerBuilderService.datePickerConfig$;

	groupBy: ReportGroupByFilter = ReportGroupFilterEnum.date;
	readonly ReportGroupFilterEnum = ReportGroupFilterEnum;

	@ViewChild(IRTranscriptsFiltersComponent) irtranscriptsFiltersComponent: IRTranscriptsFiltersComponent;

	constructor(
		private readonly timesheetFilterService: TimesheetFilterService,
		public readonly dateRangePickerBuilderService: DateRangePickerBuilderService
	) {}

	filtersChange(filters: ITimeLogFilters) {
		if (this.irtranscriptsFiltersComponent.saveFilters) {
			this.timesheetFilterService.filter = filters;
		}
		this.filters = Object.assign({}, filters);
	}

	ngOnInit(): void {}
}
