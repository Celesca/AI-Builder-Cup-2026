import { readFileSync } from 'node:fs';
import { describe, expect, it } from 'vitest';
import { session } from './session.svelte';
import type { AnalysisResponse } from './types';

const demo = JSON.parse(
	readFileSync('static/demo/xsens-004-ws10-in-l.analysis.json', 'utf8')
) as AnalysisResponse;

describe('session', () => {
	session.result = demo;

	it('derives incidents from the rules as they are now', () => {
		expect([...new Set(session.incidents.map((i) => i.ruleId))].sort()).toEqual([
			'awkward_posture',
			'bending',
			'overhead'
		]);
		session.updateRule('overhead', { threshold: 0.9 });
		expect(session.incidents.some((i) => i.ruleId === 'overhead')).toBe(false);
		session.updateRule('overhead', { threshold: 0.6 });
	});

	it('tells a changed prompt and a new rule from a ready one', () => {
		const helmet = session.rules.find((r) => r.id === 'bending')!;
		expect(session.ruleState(helmet)).toBe('ready');
		session.updateRule('bending', { prompt: 'a worker bent far over the door' });
		expect(session.ruleState(helmet)).toBe('changed');
		expect(session.staleRules.map((r) => r.id)).toContain('bending');
		session.addRule({
			id: 'goggles',
			label: 'Goggles',
			prompt: 'no goggles',
			severity: 'low',
			threshold: 0.5,
			enabled: true
		});
		expect(session.ruleState(session.rules.find((r) => r.id === 'goggles')!)).toBe('new');
		session.resetRules();
		expect(session.staleRules).toEqual([]);
	});

	it('remembers reviewed incidents and Gemba Kaizen decisions per run', () => {
		const key = session.incidents[0].key;
		expect(session.isReviewed(key)).toBe(false);
		session.toggleReviewed(key);
		expect(session.isReviewed(key)).toBe(true);
		session.toggleReviewed(key);
		expect(session.isReviewed(key)).toBe(false);

		session.setDecision('K01', 'approved');
		expect(session.decisionFor('K01')).toBe('approved');
		session.setDecision('K01', 'approved'); // choosing it again clears it
		expect(session.decisionFor('K01')).toBeNull();
	});
});
