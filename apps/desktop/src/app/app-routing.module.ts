import { NgModule } from '@angular/core';
import { ExtraOptions, RouterModule, Routes } from '@angular/router';
import { authConnectionGuard, noAuthGuard } from '@irtranscripts/desktop-ui-lib';

const routes: Routes = [
	{
		path: '',
		redirectTo: 'time-tracker',
		pathMatch: 'full'
	},
	{
		path: 'setup',
		loadComponent: () => import('@irtranscripts/desktop-ui-lib').then((m) => m.SetupComponent)
	},
	{
		path: 'time-tracker',
		canActivate: [authConnectionGuard],
		loadComponent: () => import('@irtranscripts/desktop-ui-lib').then((m) => m.TimeTrackerComponent),
		loadChildren: () => import('@irtranscripts/desktop-ui-lib').then((m) => m.RecapModule)
	},
	{
		path: 'auth',
		canActivate: [noAuthGuard],
		loadChildren: () => import('@irtranscripts/desktop-ui-lib').then((m) => m.AuthModule)
	},
	{
		path: 'screen-capture',
		loadComponent: () => import('@irtranscripts/desktop-ui-lib').then((m) => m.ScreenCaptureComponent)
	},
	{
		path: 'plugins',
		canActivate: [authConnectionGuard],
		loadChildren: () => import('@irtranscripts/desktop-ui-lib').then((m) => m.PluginRoutingModule)
	},
	{
		path: 'settings',
		loadComponent: () => import('@irtranscripts/desktop-ui-lib').then((m) => m.SettingsComponent)
	},
	{
		path: 'updater',
		loadComponent: () => import('@irtranscripts/desktop-ui-lib').then((m) => m.UpdaterComponent)
	},
	{
		path: 'viewer',
		loadComponent: () => import('@irtranscripts/desktop-ui-lib').then((m) => m.ImageViewerComponent)
	},
	{
		path: 'about',
		loadComponent: () => import('@irtranscripts/desktop-ui-lib').then((m) => m.AboutComponent)
	},
	{
		path: 'splash-screen',
		loadComponent: () => import('@irtranscripts/desktop-ui-lib').then((m) => m.SplashScreenComponent)
	},
	{
		path: 'always-on',
		loadComponent: () => import('@irtranscripts/desktop-ui-lib').then((m) => m.AlwaysOnComponent)
	},
	{
		path: '**',
		redirectTo: ''
	}
];

/**
 * Configures the router for the application.
 */
const config: ExtraOptions = {
	useHash: true
};

@NgModule({
	imports: [RouterModule.forRoot(routes, config)],
	exports: [RouterModule]
})
export class AppRoutingModule { }
