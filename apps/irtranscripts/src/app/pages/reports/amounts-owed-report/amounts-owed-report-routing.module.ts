import { NgModule } from '@angular/core';
import { Routes, RouterModule } from '@angular/router';
import { BookmarkQueryParamsResolver } from '@irtranscripts/ui-core/core';
import { DateRangePickerResolver } from '@irtranscripts/ui-core/shared';
import { AmountsOwedReportComponent } from './amounts-owed-report/amounts-owed-report.component';

const routes: Routes = [
	{
		path: '',
		component: AmountsOwedReportComponent,
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
export class AmountsOwedReportRoutingModule {}
