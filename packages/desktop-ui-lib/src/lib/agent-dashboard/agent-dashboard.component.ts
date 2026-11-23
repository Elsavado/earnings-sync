import { Component, Inject, OnInit, OnDestroy, ChangeDetectionStrategy } from '@angular/core';
import { NbMenuItem, NbSidebarState, NbLayoutModule, NbSidebarModule, NbMenuModule } from '@nebular/theme';
import { DomSanitizer, SafeResourceUrl } from '@angular/platform-browser';
import { IRTRANSCRIPTS_ENV } from '../constants';
import { IpcService } from './services/ipc.service';
import { TasksService } from './services/tasks-service';
import { RouterOutlet } from '@angular/router';

@Component({
	selector: 'ngx-agent-dashboard',
	templateUrl: './agent-dashboard.component.html',
	styleUrls: ['./agent-dashboard.component.scss'],
	changeDetection: ChangeDetectionStrategy.Eager,
	imports: [NbLayoutModule, NbSidebarModule, NbMenuModule, RouterOutlet]
})
export class AgentDashboardComponent implements OnInit, OnDestroy {
	menu: NbMenuItem[] = [
		{
			title: 'Logs',
			link: '/server-dashboard/logs', // Assuming this will be the route for logs
			icon: 'file-text-outline'
		},
		{
			title: 'Sync API Activity',
			link: '/server-dashboard/sync-activity', // Assuming this will be the route for sync activity
			icon: 'cloud-upload-outline'
		}
	];
	irtranscriptsIcon: SafeResourceUrl;
	styles = {
		btnStart: 'button-small',
		icon: 'margin-icon-small'
	};

	constructor(
		private domSanitizer: DomSanitizer,
		@Inject(IRTRANSCRIPTS_ENV)
		private readonly _environment: Record<string, any>,
		private _ipcService: IpcService,
		private _tasksService: TasksService
	) {
		this.irtranscriptsIcon = this.domSanitizer.bypassSecurityTrustResourceUrl(this._environment.PLATFORM_LOGO);
	}

	onSidebarStateChange(newState: NbSidebarState) {
		if (newState === 'compacted') {
			this.irtranscriptsIcon = this.domSanitizer.bypassSecurityTrustResourceUrl(
				this._environment.IRTRANSCRIPTS_DESKTOP_LOGO_512X512
			);
		} else {
			this.irtranscriptsIcon = this.domSanitizer.bypassSecurityTrustResourceUrl(this._environment.PLATFORM_LOGO);
		}
	}

	ngOnInit(): void {
		this._ipcService.ipcListen();
		this._tasksService.loadTaskStatus();
	}

	ngOnDestroy(): void {
		this._ipcService.ipcRemoveListener();
	}
}
