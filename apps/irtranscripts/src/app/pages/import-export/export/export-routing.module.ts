import { NgModule } from '@angular/core';
import { Routes, RouterModule } from '@angular/router';
import { PermissionsEnum } from '@irtranscripts/contracts';
import { PermissionsGuard } from '@irtranscripts/ui-core/core';
import { ExportComponent } from './export.component';

const routes: Routes = [
	{
		path: '',
		component: ExportComponent,
		canActivate: [PermissionsGuard],
		data: {
			permissions: {
				only: [PermissionsEnum.EXPORT_ADD],
				redirectTo: '/pages/settings'
			}
		}
	}
];

@NgModule({
	imports: [RouterModule.forChild(routes)],
	exports: [RouterModule]
})
export class ExportRoutingModule {}
