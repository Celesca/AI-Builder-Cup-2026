import { readFileSync } from 'node:fs';
import { describe, expect, it } from 'vitest';
import { deriveIncidents, fmt, frameStep, peakConfidence } from './analysis';
import { DEFAULT_RULES, newRuleId } from './rules';
import type { AnalysisResponse, Rule, TimelineFrame } from './types';

const demo = JSON.parse(
	readFileSync('static/demo/xsens-004-ws10-in-l.analysis.json', 'utf8')
) as AnalysisResponse;
const frames = demo.safety.activity.timeline;

const rules = (patch: Partial<Record<string, Partial<Rule>>> = {}): Rule[] =>
	DEFAULT_RULES.map((rule) => ({ ...rule, ...patch[rule.id] }));

describe('deriveIncidents', () => {
	it('reproduces the backend incidents from the per-frame confidences', () => {
		const derived = deriveIncidents(
			frames,
			rules(),
			demo.safety.sample_fps,
			demo.safety.safety_events
		);
		const key = (e: {
			ruleId?: string;
			rule_id?: string;
			start?: number;
			start_time?: number;
			end?: number;
			end_time?: number;
		}) => `${e.ruleId ?? e.rule_id}:${e.start ?? e.start_time}-${e.end ?? e.end_time}`;
		expect(derived.map(key).sort()).toEqual(demo.safety.safety_events.map(key).sort());
		const bending = derived.find((i) => i.ruleId === 'bending')!;
		const backend = demo.safety.safety_events.find((e) => e.rule_id === 'bending')!;
		expect(bending.peak).toBeCloseTo(backend.peak_confidence, 6);
		expect(bending.description).toBe(backend.description);
		expect(bending.snapshot).toBe(backend.snapshot);
	});

	it('drops a one-frame false alarm when its threshold is raised', () => {
		const at = (threshold: number) =>
			deriveIncidents(frames, rules({ overhead: { threshold } }), 1).filter(
				(i) => i.ruleId === 'overhead'
			);
		expect(at(0.6)).toHaveLength(1);
		expect(at(0.9)).toHaveLength(0);
	});

	it('shows near misses when a threshold is lowered, and ignores disabled rules', () => {
		const total = (list: { ruleId: string; duration: number }[]) =>
			list.filter((i) => i.ruleId === 'awkward_posture').reduce((n, i) => n + i.duration, 0);
		const strict = deriveIncidents(frames, rules(), 1);
		const loose = deriveIncidents(frames, rules({ awkward_posture: { threshold: 0.4 } }), 1);
		expect(total(loose)).toBeGreaterThan(total(strict));
		expect(
			deriveIncidents(frames, rules({ bending: { enabled: false } }), 1).some(
				(i) => i.ruleId === 'bending'
			)
		).toBe(false);
	});

	it('knows nothing about a rule the run has no data for', () => {
		const custom: Rule = {
			id: 'custom',
			label: 'Custom',
			prompt: 'x',
			severity: 'low',
			threshold: 0.5,
			enabled: true
		};
		expect(deriveIncidents(frames, [custom], 1)).toEqual([]);
		expect(peakConfidence(frames, 'custom')).toBeNull();
		expect(peakConfidence(frames, 'overhead')).toBeCloseTo(0.85);
	});

	it('splits incidents on gaps longer than two seconds and sorts by time', () => {
		const make = (t: number, v: number): TimelineFrame => ({
			timestamp: t,
			frame_idx: t,
			activity: 'working',
			category: 'VA',
			confidence: 0.9,
			rule_confidences: { r: v }
		});
		const synthetic = [0, 1, 2, 3, 4, 5, 6, 7].map((t) =>
			make(t, [0, 1, 2, 5, 6, 7].includes(t) ? 0.9 : 0.1)
		);
		const rule: Rule = {
			id: 'r',
			label: 'R',
			prompt: 'p',
			severity: 'high',
			threshold: 0.6,
			enabled: true
		};
		const incidents = deriveIncidents(synthetic, [rule], 1);
		expect(incidents.map((i) => [i.start, i.end, i.frames])).toEqual([
			[0, 3, 3],
			[5, 8, 3]
		]);
	});
});

describe('helpers', () => {
	it('formats times', () => {
		expect([fmt(0), fmt(75.9), fmt(3600), fmt(-1), fmt(NaN)]).toEqual([
			'00:00',
			'01:15',
			'60:00',
			'00:00',
			'00:00'
		]);
	});

	it('derives the frame step from fps or from the timestamps', () => {
		expect(frameStep(frames, 2)).toBe(0.5);
		expect(frameStep(frames, 0)).toBe(1);
	});

	it('makes unique backend-safe rule ids', () => {
		expect(newRuleId('Hard hat!', ['helmet'])).toBe('hard_hat');
		expect(newRuleId('Hard hat!', ['hard_hat'])).toBe('hard_hat_2');
		expect(newRuleId('日本語', [])).toBe('rule');
	});
});

describe('bundled demo', () => {
	const manifest = JSON.parse(readFileSync('static/demo/manifest.json', 'utf8')) as {
		clips: { id: string; video: string; analysis: string; duration: number }[];
	};

	it('lists clips whose files exist and whose analysis has the fields the pages read', () => {
		expect(manifest.clips.length).toBeGreaterThan(0);
		for (const clip of manifest.clips) {
			expect(() => readFileSync(`static${clip.video}`)).not.toThrow();
			const analysis = JSON.parse(
				readFileSync(`static${clip.analysis}`, 'utf8')
			) as AnalysisResponse;
			expect(analysis.safety.activity.timeline.length).toBeGreaterThan(0);
			expect(analysis.safety.rules.length).toBeGreaterThan(0);
			expect(analysis.lss.metrics.waste_by_category).toBeDefined();
			expect(analysis.lss.lss_cards.every((c) => Array.isArray(c.evidence))).toBe(true);
			expect(Math.round(analysis.safety.video_duration)).toBe(clip.duration);
		}
	});

	it('is a real analysis of the CarDA clip, labelled with the model that produced it', () => {
		expect(demo.demo?.synthetic).not.toBe(true);
		expect(demo.safety.model).not.toMatch(/cached demo/);
		expect(demo.lss.context.station_name).toBe('WS10');
		expect(demo.lss.context.cycle_time_s).toBe(240);
	});
});
