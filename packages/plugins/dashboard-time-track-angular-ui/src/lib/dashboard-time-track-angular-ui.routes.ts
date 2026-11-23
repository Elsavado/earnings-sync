import { Route } from '@angular/router';
import { BookmarkQueryParamsResolver } from '@irtranscripts/ui-core/core';
import { DateRangePickerResolver } from '@irtranscripts/ui-core/shared';
import { TimeTrackingComponent } from './components/time-tracking/time-tracking.component';

/**
 * Creates the child routes for the Time Tracking module.
 *
 * @returns Angular Route array for the time tracking feature.
 */
export function createTimeTrackingRoutes(): Route[] {
	return [
		{
			path: '',
			component: TimeTrackingComponent,
			data: {
				datePicker: {
					unitOfTime: 'week'
				}
			},
			resolve: {
				dates: DateRangePickerResolver,
				bookmarkParams: BookmarkQueryParamsResolver
			}
		}
	];
}

