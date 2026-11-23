import { NgModule } from '@angular/core';
import { NbCardModule, NbIconModule, NbSelectModule, NbSpinnerModule } from '@nebular/theme';
import {
	DailyGridModule,
	DailyStatisticsModule,
	IRTranscriptsFiltersModule,
	LineChartModule,
	SharedModule
} from '@irtranscripts/ui-core/shared';
import { TranslatePipe } from '@ngx-translate/core';
import { TimeReportsRoutingModule } from './time-reports-routing.module';
import { TimeReportsComponent } from './time-reports/time-reports.component';

@NgModule({
	declarations: [TimeReportsComponent],
	imports: [
		NbCardModule,
		NbIconModule,
		NbSelectModule,
		NbSpinnerModule,
		TranslatePipe,
		SharedModule,
		DailyGridModule,
		DailyStatisticsModule,
		TimeReportsRoutingModule,
		LineChartModule,
		IRTranscriptsFiltersModule
	]
})
export class TimeReportsModule {}
