import { NgModule } from '@angular/core';
import { CommonModule } from '@angular/common';
import { AppointmentCalendarModule } from '@irtranscripts/ui-core/shared';
import { AppointmentRoutingModule } from './appointment-routing.module';

@NgModule({
	imports: [CommonModule, AppointmentCalendarModule, AppointmentRoutingModule],
	providers: []
})
export class AppointmentModule {}
