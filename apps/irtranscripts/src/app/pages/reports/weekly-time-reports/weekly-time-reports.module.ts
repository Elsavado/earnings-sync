import { NgModule } from '@angular/core';
import { TranslatePipe } from '@ngx-translate/core';
import { NbIconModule, NbSpinnerModule, NbCardModule, NbBadgeModule } from '@nebular/theme';
import {
	DailyStatisticsModule,
	IRTranscriptsFiltersModule,
	LineChartModule,
	NoDataMessageModule,
	SharedModule
} from '@irtranscripts/ui-core/shared';
import { WeeklyTimeReportsRoutingModule } from './weekly-time-reports-routing.module';
import { WeeklyTimeReportsComponent } from './weekly-time-reports/weekly-time-reports.component';

@NgModule({
	declarations: [WeeklyTimeReportsComponent],
	imports: [
		SharedModule,
		WeeklyTimeReportsRoutingModule,
		LineChartModule,
		DailyStatisticsModule,
		TranslatePipe,
		NbIconModule,
		NbSpinnerModule,
		NbCardModule,
		IRTranscriptsFiltersModule,
		NbBadgeModule,
		NoDataMessageModule
	]
})
export class WeeklyTimeReportsModule {}
