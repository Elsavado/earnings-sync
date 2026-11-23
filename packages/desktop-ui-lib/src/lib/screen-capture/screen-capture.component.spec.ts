import { ComponentFixture, TestBed } from '@angular/core/testing';
import { ScreenCaptureComponent } from './screen-capture.component';
import { environment } from '@irtranscripts/ui-config';
import { IRTRANSCRIPTS_ENV } from '../constants';
describe('ScreenCaptureComponent', () => {
	let component: ScreenCaptureComponent;
	let fixture: ComponentFixture<ScreenCaptureComponent>;
	beforeEach(async () => {
		await TestBed.configureTestingModule({
			imports: [ScreenCaptureComponent],
			// The desktop apps provide this library's IRTRANSCRIPTS_ENV token as the web environment plus their own
			// flags (apps/desktop/src/main.ts). The web environment is enough for a render.
			providers: [{ provide: IRTRANSCRIPTS_ENV, useValue: environment }]
		}).compileComponents();
	});
	beforeEach(() => {
		fixture = TestBed.createComponent(ScreenCaptureComponent);
		component = fixture.componentInstance;
		fixture.detectChanges();
	});
	it('should create', () => {
		expect(component).toBeTruthy();
	});
});
