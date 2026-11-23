import { Injectable } from '@angular/core';
import { HttpClient } from '@angular/common/http';
import { firstValueFrom } from 'rxjs';
import {
	ICandidateSourceFindInput,
	ICandidateSource,
	ICandidateSourceCreateInput,
	IPagination
} from '@irtranscripts/contracts';
import { toParams } from '@irtranscripts/ui-core/common';
import { API_PREFIX } from '@irtranscripts/ui-core/common';

@Injectable({
	providedIn: 'root'
})
export class CandidateSourceService {
	constructor(private readonly http: HttpClient) {}

	getAll(where?: ICandidateSourceFindInput): Promise<IPagination<ICandidateSource>> {
		return firstValueFrom(
			this.http.get<IPagination<ICandidateSource>>(`${API_PREFIX}/candidate-source`, {
				params: toParams({ where })
			})
		);
	}

	create(input: ICandidateSourceCreateInput): Promise<ICandidateSource> {
		return firstValueFrom(this.http.post<ICandidateSource>(`${API_PREFIX}/candidate-source`, input));
	}
}
