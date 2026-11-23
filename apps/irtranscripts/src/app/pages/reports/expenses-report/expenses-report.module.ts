import { NgModule } from '@angular/core';
import { NbIconModule, NbSpinnerModule, NbCardModule, NbSelectModule } from '@nebular/theme';
import { TranslatePipe } from '@ngx-translate/core';
import {
	ExpenseCategorySelectModule,
	ExpensesReportGridModule,
	IRTranscriptsFiltersModule,
	LineChartModule,
	SharedModule
} from '@irtranscripts/ui-core/shared';
import { ExpensesReportRoutingModule } from './expenses-report-routing.module';
import { ExpensesReportComponent } from './expenses-report/expenses-report.component';

@NgModule({
	declarations: [ExpensesReportComponent],
	imports: [
		ExpensesReportRoutingModule,
		TranslatePipe,
		SharedModule,
		NbIconModule,
		NbSpinnerModule,
		NbCardModule,
		NbSelectModule,
		ExpensesReportGridModule,
		LineChartModule,
		IRTranscriptsFiltersModule,
		ExpenseCategorySelectModule
	]
})
export class ExpensesReportModule {}
