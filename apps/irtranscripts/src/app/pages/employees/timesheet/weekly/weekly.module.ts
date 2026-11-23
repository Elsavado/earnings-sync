// tslint:disable: nx-enforce-module-boundaries
import { NgModule } from '@angular/core';
import {
	NbDatepickerModule,
	NbIconModule,
	NbButtonModule,
	NbDialogModule,
	NbSpinnerModule,
	NbPopoverModule,
	NbCardModule,
	NbCheckboxModule
} from '@nebular/theme';
import { NgxPermissionsModule } from 'ngx-permissions';
import { TranslatePipe } from '@ngx-translate/core';
import {
	EditTimeLogModalModule,
	IRTranscriptsFiltersModule,
	NoDataMessageModule,
	SharedModule,
	TableComponentsModule,
	ViewTimeLogModule
} from '@irtranscripts/ui-core/shared';
import { WeeklyRoutingModule } from './weekly-routing.module';
import { WeeklyComponent } from './weekly/weekly.component';

@NgModule({
	declarations: [WeeklyComponent],
	imports: [
		WeeklyRoutingModule,
		TranslatePipe,
		NgxPermissionsModule.forChild(),
		NbDatepickerModule,
		NbIconModule,
		NbButtonModule,
		SharedModule,
		IRTranscriptsFiltersModule,
		EditTimeLogModalModule,
		NbDialogModule,
		NbSpinnerModule,
		NbButtonModule,
		NbPopoverModule,
		ViewTimeLogModule,
		NbCardModule,
		NbCheckboxModule,
		TableComponentsModule,
		NoDataMessageModule
	]
})
export class WeeklyModule {}
