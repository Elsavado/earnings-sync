import { ComponentFixture, TestBed } from '@angular/core/testing';
import { IRTranscriptsFiltersComponent } from './irtranscripts-filters.component';
import { IRTranscriptsFiltersModule } from './irtranscripts-filters.module';
describe('IRTranscriptsFiltersComponent', () => {
	let component: IRTranscriptsFiltersComponent;
	let fixture: ComponentFixture<IRTranscriptsFiltersComponent>;
	beforeEach(async () => {
		await TestBed.configureTestingModule({
			// Not standalone: import its NgModule. (This stub imported `IRTranscriptsRangePickerComponent`, a class the file
			// does not export, so it declared `undefined`.)
			imports: [IRTranscriptsFiltersModule]
		}).compileComponents();
	});
	beforeEach(() => {
		fixture = TestBed.createComponent(IRTranscriptsFiltersComponent);
		component = fixture.componentInstance;
		fixture.detectChanges();
	});
	it('should create', () => {
		expect(component).toBeTruthy();
	});
});
