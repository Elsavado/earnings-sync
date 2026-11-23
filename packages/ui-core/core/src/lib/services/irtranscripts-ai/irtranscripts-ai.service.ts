import { Injectable } from '@angular/core';
import { HttpClient } from '@angular/common/http';
import { Observable } from 'rxjs';
import { IIntegrationAICreateInput, IIntegrationTenant } from '@irtranscripts/contracts';
import { API_PREFIX } from '@irtranscripts/ui-core/common';
import { CrudService } from '../crud/crud.service';

@Injectable({
	providedIn: 'root'
})
export class IRTranscriptsAIService extends CrudService<IIntegrationTenant> {
	static readonly API_URL = `${API_PREFIX}/integration/ai`;

	constructor(readonly _http: HttpClient) {
		super(_http, IRTranscriptsAIService.API_URL);
	}

	/**
	 * Create a new integration AI.
	 *
	 * @param input - Data for creating the integration AI, of type IIntegrationAICreateInput.
	 * @returns An Observable of type IIntegrationTenant representing the created integration AI.
	 */
	override create(input: IIntegrationAICreateInput): Observable<IIntegrationTenant> {
		return this._http.post<IIntegrationTenant>(`${IRTranscriptsAIService.API_URL}`, input);
	}
}
