import { NgModule } from '@angular/core';
import { Routes, RouterModule } from '@angular/router';
import { BookmarkQueryParamsResolver } from '@irtranscripts/ui-core/core';
import { DateRangePickerResolver } from '@irtranscripts/ui-core/shared';
import { PaymentReportComponent } from './payment-report/payment-report.component';

const routes: Routes = [
	{
		path: '',
		component: PaymentReportComponent,
		data: {
			datePicker: {
				unitOfTime: 'week'
			},
			selectors: {
				employee: false
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
export class PaymentReportRoutingModule {}
