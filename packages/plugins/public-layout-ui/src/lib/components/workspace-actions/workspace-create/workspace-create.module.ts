import { NgModule } from '@angular/core';
import { CommonModule } from '@angular/common';
import { ReactiveFormsModule } from '@angular/forms';
import { RouterModule, Routes } from '@angular/router';
import {
	NbButtonModule,
	NbIconModule,
	NbCardModule,
	NbInputModule,
	NbFormFieldModule,
	NbSpinnerModule,
	NbTooltipModule
} from '@nebular/theme';
import { TranslatePipe } from '@ngx-translate/core';
import { SharedModule, OrganizationsStepFormModule, PasswordFormFieldModule } from '@irtranscripts/ui-core/shared';
import { ThemeModule } from '@irtranscripts/ui-core/theme';
import { TenantService, OrganizationsService, UsersService, WorkspaceAuthService } from '@irtranscripts/ui-core/core';
import { WorkspaceCreateComponent } from './workspace-create.component';
import { CountdownTimerService, WorkspaceSharedModule } from '../shared';

const routes: Routes = [
	{
		path: '',
		component: WorkspaceCreateComponent
	}
];

@NgModule({
	declarations: [WorkspaceCreateComponent],
	imports: [
		CommonModule,
		ReactiveFormsModule,
		RouterModule.forChild(routes),
		NbButtonModule,
		NbIconModule,
		NbCardModule,
		NbInputModule,
		NbFormFieldModule,
		NbSpinnerModule,
		NbTooltipModule,
		TranslatePipe,
		SharedModule,
		OrganizationsStepFormModule,
		PasswordFormFieldModule,
		ThemeModule,
		WorkspaceSharedModule
	],
	providers: [TenantService, OrganizationsService, UsersService, WorkspaceAuthService, CountdownTimerService]
})
export class WorkspaceCreateModule {}
