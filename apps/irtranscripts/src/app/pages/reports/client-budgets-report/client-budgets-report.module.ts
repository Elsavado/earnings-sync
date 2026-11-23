import { NgModule } from '@angular/core';
import { NbIconModule, NbSpinnerModule, NbCardModule, NbSelectModule } from '@nebular/theme';
import { TranslatePipe } from '@ngx-translate/core';
import {
	IRTranscriptsFiltersModule,
	LineChartModule,
	NoDataMessageModule,
	ProgressStatusModule,
	SharedModule,
	TableComponentsModule
} from '@irtranscripts/ui-core/shared';
import { ClientBudgetsReportRoutingModule } from './client-budgets-report-routing.module';
import { ClientBudgetsReportComponent } from './client-budgets-report/client-budgets-report.component';

@NgModule({
	declarations: [ClientBudgetsReportComponent],
	imports: [
		ClientBudgetsReportRoutingModule,
		SharedModule,
		TranslatePipe,
		NbIconModule,
		NbSpinnerModule,
		NbCardModule,
		NbSelectModule,
		LineChartModule,
		ProgressStatusModule,
		IRTranscriptsFiltersModule,
		TableComponentsModule,
		NoDataMessageModule
	]
})
export class ClientBudgetsReportModule {}
