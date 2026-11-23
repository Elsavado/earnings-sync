import { ComponentFixture, TestBed } from '@angular/core/testing';
import { IRTranscriptsFormComponent } from './irtranscripts-form.component';
describe('IRTranscriptsFormComponent', () => {
	let component: IRTranscriptsFormComponent;
	let fixture: ComponentFixture<IRTranscriptsFormComponent>;
	beforeEach(async () => {
		await TestBed.configureTestingModule({
			imports: [IRTranscriptsFormComponent]
		}).compileComponents();
		fixture = TestBed.createComponent(IRTranscriptsFormComponent);
		component = fixture.componentInstance;
		fixture.detectChanges();
	});
	it('should create', () => {
		expect(component).toBeTruthy();
	});
});
