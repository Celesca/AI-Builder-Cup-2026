// Safety rules the manager edits. Each enabled rule is sent to the Safety Agent as a free-text prompt
// ("is <prompt> happening in this frame?"), so prompts describe the violation, not the safe state.
// The defaults live in default-rules.json so scripts/add-demo-clip.mjs and the bundled demo use the same ids.
import defaultRules from './default-rules.json';
import type { Level, Rule } from './types';

export const DEFAULT_RULES: Rule[] = defaultRules as Rule[];

/** Extra rules offered as one-click additions. */
export const PRESET_RULES: Rule[] = [
	{
		id: 'goggles',
		label: 'Safety goggles',
		prompt: 'a person working without safety goggles or safety glasses',
		severity: 'medium',
		threshold: 0.6,
		enabled: true
	},
	{
		id: 'phone_use',
		label: 'Phone use',
		prompt: 'a person using a mobile phone',
		severity: 'medium',
		threshold: 0.6,
		enabled: true
	},
	{
		id: 'person_down',
		label: 'Person down',
		prompt: 'a person lying on the floor or falling down',
		severity: 'high',
		threshold: 0.6,
		enabled: true
	},
	{
		id: 'guard_open',
		label: 'Machine guard open',
		prompt: 'a person reaching into a machine whose safety guard is open',
		severity: 'high',
		threshold: 0.6,
		enabled: true
	}
];

export const SEVERITIES: Level[] = ['low', 'medium', 'high'];
export const MAX_PROMPT_LENGTH = 300;

const STORAGE_KEY = 'valz-rules-v1';

/** A short, unique, backend-safe id for a new rule. */
export function newRuleId(label: string, taken: Iterable<string>): string {
	const used = new Set(taken);
	const base =
		label
			.toLowerCase()
			.replace(/[^a-z0-9]+/g, '_')
			.replace(/^_+|_+$/g, '')
			.slice(0, 24) || 'rule';
	let id = base;
	for (let n = 2; used.has(id); n++) id = `${base}_${n}`;
	return id;
}

function isRule(value: unknown): value is Rule {
	if (typeof value !== 'object' || value === null) return false;
	const r = value as Record<string, unknown>;
	return (
		typeof r.id === 'string' &&
		typeof r.label === 'string' &&
		typeof r.prompt === 'string' &&
		typeof r.threshold === 'number' &&
		typeof r.enabled === 'boolean' &&
		SEVERITIES.includes(r.severity as Level)
	);
}

export function loadRules(): Rule[] {
	try {
		const parsed = JSON.parse(localStorage.getItem(STORAGE_KEY) ?? 'null');
		if (Array.isArray(parsed) && parsed.length && parsed.every(isRule)) return parsed;
	} catch {
		// storage unavailable or corrupt: use the defaults
	}
	return structuredClone(DEFAULT_RULES);
}

export function saveRules(rules: Rule[]) {
	try {
		localStorage.setItem(STORAGE_KEY, JSON.stringify(rules));
	} catch {
		// private mode or full: rules still live in memory
	}
}
