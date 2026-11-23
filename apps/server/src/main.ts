import { provideHttpClient, withInterceptorsFromDi, withXhr } from '@angular/common/http';
import {
	enableProdMode,
	ErrorHandler,
	importProvidersFrom,
	inject,
	provideAppInitializer,
	provideZoneChangeDetection
} from '@angular/core';
import { bootstrapApplication, BrowserModule } from '@angular/platform-browser';
import { provideAnimations } from '@angular/platform-browser/animations';
import { Router, RouterModule } from '@angular/router';
import { akitaConfig, persistState } from '@datorama/akita';
import {
	ElectronService,
	IRTRANSCRIPTS_ENV,
	IRTranscriptsStorageService,
	LanguageModule,
	LoggerService,
	NgxDesktopThemeModule,
	providePluginInitializers,
	providePluginsEffects,
	Store
} from '@irtranscripts/desktop-ui-lib';
import { environment as irtranscriptsEnvironment } from '@irtranscripts/ui-config';
import { provideI18n } from '@irtranscripts/ui-core/i18n';
import { TablerIconsModule } from '@irtranscripts/ui-core/icons';
import {
	NbDialogModule,
	NbDialogService,
	NbIconLibraries,
	NbMenuModule,
	NbSidebarModule,
	NbToastrModule
} from '@nebular/theme';
import { provideEffectsManager } from '@ngneat/effects-ng';
import * as Sentry from '@sentry/angular';
import { AppRoutingModule } from './app/app-routing.module';
import { AppComponent } from './app/app.component';
import { AppService } from './app/app.service';
import { initializeSentry } from './app/sentry';
import { environment } from './environments/environment';

if (environment.production) {
	enableProdMode();
}

if (environment.SENTRY_DSN) {
	if (environment.SENTRY_DSN === 'DOCKER_SENTRY_DSN') {
		console.warn('You are running inside Docker but does not have SENTRY_DSN env set');
	} else {
		console.log('Enabling Sentry');
		initializeSentry();
	}
}

bootstrapApplication(AppComponent, {
	providers: [
		provideEffectsManager(),
		providePluginsEffects(),
		providePluginInitializers(),
		provideZoneChangeDetection(),
		importProvidersFrom(
			NbDialogModule.forRoot(),
			NbSidebarModule.forRoot(),
			NbToastrModule.forRoot(),
			BrowserModule,
			RouterModule,
			AppRoutingModule,
			NbMenuModule.forRoot(),
			NgxDesktopThemeModule,
			TablerIconsModule,
			LanguageModule.forRoot()
		),
		provideI18n({ extend: true }),
		AppService,
		NbDialogService,
		ElectronService,
		LoggerService,
		Store,
		provideAppInitializer(() => {
			const storage = inject(IRTranscriptsStorageService);
			persistState({
				key: '_irtranscriptsStore',
				enableInNonBrowser: true,
				storage
			});
			akitaConfig({
				resettable: true
			});
		}),
		{
			provide: ErrorHandler,
			useValue: Sentry.createErrorHandler({
				showDialog: true
			})
		},
		{
			provide: Sentry.TraceService,
			deps: [Router]
		},
		provideAppInitializer(() => {
			const initializerFn = ((trace: Sentry.TraceService) => () => {})(inject(Sentry.TraceService));
			return initializerFn();
		}),
		provideAppInitializer(() => {
			const iconLibraries = inject(NbIconLibraries);

			iconLibraries.registerFontPack('font-awesome', {
				packClass: 'fas',
				iconClassPrefix: 'fa'
			});

			iconLibraries.setDefaultPack('eva');
		}),
		{
			provide: IRTRANSCRIPTS_ENV,
			useValue: {
				...irtranscriptsEnvironment,
				...environment
			}
		},
		provideHttpClient(withXhr(), withInterceptorsFromDi()),
		provideAnimations()
	]
}).catch((err) => console.error(err));
