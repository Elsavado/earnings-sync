import { NgModule } from '@angular/core';
import { Routes, RouterModule } from '@angular/router';
import { BookmarkQueryParamsResolver } from '@irtranscripts/ui-core/core';
import { DateRangePickerResolver } from '@irtranscripts/ui-core/shared';
import { CalendarComponent } from './calendar/calendar.component';

const routes: Routes = [
	{
		path: '',
		component: CalendarComponent,
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

@NgModule({
	imports: [RouterModule.forChild(routes)],
	exports: [RouterModule]
})
export class CalendarRoutingModule {}
