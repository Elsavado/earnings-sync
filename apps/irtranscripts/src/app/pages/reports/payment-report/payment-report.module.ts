import { NgModule } from '@angular/core';
import { NbIconModule, NbSpinnerModule, NbCardModule, NbSelectModule } from '@nebular/theme';
import { TranslatePipe } from '@ngx-translate/core';
import {
	ContactSelectModule,
	CurrencyModule,
	IRTranscriptsFiltersModule,
	LineChartModule,
	PaymentReportGridModule,
	SharedModule
} from '@irtranscripts/ui-core/shared';
import { PaymentReportRoutingModule } from './payment-report-routing.module';
import { PaymentReportComponent } from './payment-report/payment-report.component';

@NgModule({
	declarations: [PaymentReportComponent],
	imports: [
		PaymentReportRoutingModule,
		SharedModule,
		TranslatePipe,
		NbIconModule,
		NbSpinnerModule,
		NbCardModule,
		NbSelectModule,
		LineChartModule,
		PaymentReportGridModule,
		IRTranscriptsFiltersModule,
		ContactSelectModule,
		CurrencyModule
	]
})
export class PaymentReportModule {}
