import { NgModule } from '@angular/core';
import { NbIconModule, NbSpinnerModule, NbCardModule, NbSelectModule } from '@nebular/theme';
import { TranslatePipe } from '@ngx-translate/core';
import { AmountsOwedGridModule, IRTranscriptsFiltersModule, LineChartModule, SharedModule } from '@irtranscripts/ui-core/shared';
import { AmountsOwedReportRoutingModule } from './amounts-owed-report-routing.module';
import { AmountsOwedReportComponent } from './amounts-owed-report/amounts-owed-report.component';

@NgModule({
	declarations: [AmountsOwedReportComponent],
	imports: [
		AmountsOwedReportRoutingModule,
		SharedModule,
		TranslatePipe,
		NbIconModule,
		NbSpinnerModule,
		NbCardModule,
		NbSelectModule,
		AmountsOwedGridModule,
		LineChartModule,
		IRTranscriptsFiltersModule
	]
})
export class AmountsOwedReportModule {}
