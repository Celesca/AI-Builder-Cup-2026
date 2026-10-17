import { describe, expect, it } from 'vitest';
import { normalizeBackendUrl, uploadTarget } from './backend-url';

describe('normalizeBackendUrl', () => {
	it('adds http, drops trailing slashes and keeps a path prefix', () => {
		expect(normalizeBackendUrl('valz.example.com/')).toBe('http://valz.example.com');
		expect(normalizeBackendUrl(' https://valz.example.com:8443/api/ ')).toBe(
			'https://valz.example.com:8443/api'
		);
		expect(normalizeBackendUrl('localhost:8000')).toBe('http://localhost:8000');
	});

	it('leaves a typed scheme alone and never doubles it', () => {
		expect(normalizeBackendUrl('https://valz.example.com')).toBe(
			'https://valz.example.com'
		);
		expect(normalizeBackendUrl('HTTP://valz.example.com')).toBe('http://valz.example.com');
		expect(normalizeBackendUrl('https://https://valz.example.com')).toBe(
			'https://valz.example.com'
		);
		expect(normalizeBackendUrl('http://http://localhost:8000/')).toBe('http://localhost:8000');
	});

	it('treats empty as "use the server default"', () => {
		expect(normalizeBackendUrl('  ')).toBe('');
	});

	it('rejects other schemes and nonsense', () => {
		expect(normalizeBackendUrl('file:///etc/passwd')).toBeNull();
		expect(normalizeBackendUrl('ftp://host')).toBeNull();
		expect(normalizeBackendUrl('http://')).toBeNull();
	});
});

describe('uploadTarget', () => {
	it('uses the /api proxy when no backend was chosen', () => {
		expect(uploadTarget('gemba/analyze/upload', '', 'https:')).toEqual({
			url: '/api/gemba/analyze/upload'
		});
	});

	it('sends straight to the chosen backend', () => {
		expect(uploadTarget('video/preview', 'https://gemba.example.com', 'https:')).toEqual({
			url: 'https://gemba.example.com/video/preview'
		});
		expect(uploadTarget('video/preview', 'http://localhost:8000', 'http:')).toEqual({
			url: 'http://localhost:8000/video/preview'
		});
	});

	it('explains mixed content instead of failing silently', () => {
		const target = uploadTarget('video/preview', 'http://gemba.example.com', 'https:');
		expect('error' in target && target.error).toContain('https');
	});
});
