import { NgModule } from '@angular/core';
import { NbSelectModule } from '@nebular/theme';
import { TranslatePipe } from '@ngx-translate/core';
import { DailyGridModule, DailyStatisticsModule, IRTranscriptsFiltersModule, SharedModule } from '@irtranscripts/ui-core/shared';
import { TimeActivitiesRoutingModule } from './time-activities-routing.module';
import { TimeActivitiesComponent } from './time-activities/time-activities.component';

@NgModule({
	declarations: [TimeActivitiesComponent],
	imports: [
		NbSelectModule,
		TranslatePipe,
		TimeActivitiesRoutingModule,
		DailyGridModule,
		DailyStatisticsModule,
		SharedModule,
		IRTranscriptsFiltersModule
	]
})
export class TimeAndActivitiesModule {}
