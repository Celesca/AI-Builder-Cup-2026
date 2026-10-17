// Pure functions over the pipeline result: incidents from per-frame confidences, labels, formatting.
import type { BackendEvent, Category, Incident, Rule, TimelineFrame } from './types';

/** Seconds between flagged frames that still count as one incident (the backend's segment_gap default). */
export const INCIDENT_GAP_S = 2;

export function fmt(seconds: number): string {
	if (!Number.isFinite(seconds) || seconds < 0) return '00:00';
	const m = Math.floor(seconds / 60);
	const s = Math.floor(seconds % 60);
	return `${String(m).padStart(2, '0')}:${String(s).padStart(2, '0')}`;
}

export function fmtRange(start: number, end: number): string {
	return `${fmt(start)}–${fmt(end)}`;
}

export const pct = (fraction: number) => Math.round(Math.min(1, Math.max(0, fraction)) * 100);

export function hoursLabel(hours: number): string {
	return `${hours.toFixed(hours < 10 ? 1 : 0)} h`;
}

/** Seconds covered by one sampled frame. */
export function frameStep(frames: TimelineFrame[], sampleFps: number): number {
	if (sampleFps > 0) return 1 / sampleFps;
	return frames.length > 1 ? frames[1].timestamp - frames[0].timestamp : 1;
}

/**
 * Group the frames where a rule's confidence reached its threshold into incidents.
 * Mirrors ai_backend's build_safety_events, so moving a threshold gives what a re-run would.
 */
export function deriveIncidents(
	frames: TimelineFrame[],
	rules: Rule[],
	sampleFps: number,
	backendEvents: BackendEvent[] = []
): Incident[] {
	const step = frameStep(frames, sampleFps);
	const incidents: Incident[] = [];

	for (const rule of rules) {
		if (!rule.enabled) continue;
		const hits = frames.filter((f) => (f.rule_confidences[rule.id] ?? -1) >= rule.threshold);
		let group: TimelineFrame[] = [];

		const close = () => {
			const confs = group.map((f) => f.rule_confidences[rule.id]);
			const peakIndex = confs.indexOf(Math.max(...confs));
			const start = group[0].timestamp;
			const last = group[group.length - 1].timestamp;
			const end = last + step;
			// Reuse the backend's description and snapshot when one of its incidents for this rule overlaps
			const match = backendEvents.find(
				(e) => e.rule_id === rule.id && e.start_time < end && e.end_time > start
			);
			incidents.push({
				key: `${rule.id}@${start}`,
				ruleId: rule.id,
				label: rule.label,
				severity: rule.severity,
				start,
				end,
				duration: last - start + step,
				peak: Math.max(...confs),
				mean: confs.reduce((a, b) => a + b, 0) / confs.length,
				frames: group.length,
				keyTime: group[peakIndex].timestamp,
				prompt: rule.prompt,
				description: match?.description ?? '',
				snapshot:
					match && Math.abs(match.key_timestamp - group[peakIndex].timestamp) <= 1
						? match.snapshot
						: null
			});
		};

		for (const frame of hits) {
			if (group.length && frame.timestamp - group[group.length - 1].timestamp > INCIDENT_GAP_S) {
				close();
				group = [];
			}
			group.push(frame);
		}
		if (group.length) close();
	}

	return incidents.sort((a, b) => a.start - b.start);
}

/** The strongest confidence a rule reached anywhere in the run (null when the run has no data for it). */
export function peakConfidence(frames: TimelineFrame[], ruleId: string): number | null {
	const values = frames.map((f) => f.rule_confidences[ruleId]).filter((v) => v !== undefined);
	return values.length ? Math.max(...values) : null;
}

const SEVERITY_RANK: Record<string, number> = { high: 3, medium: 2, low: 1 };
export const severityRank = (level: string) => SEVERITY_RANK[level] ?? 0;

// ---- activity classes ---------------------------------------------------------------------------------------

export const CATEGORY_LABEL: Record<Category, string> = {
	VA: 'Value-adding',
	NNVA: 'Inspection',
	NVA_MOTION: 'Motion',
	NVA_TRANSPORT: 'Transport',
	NVA_WAITING: 'Waiting',
	NVA_SEARCH: 'Searching',
	NO_PERSON: 'No person',
	UNCERTAIN: 'Unclear'
};

/** Order for legends and breakdowns. */
export const CATEGORY_ORDER: Category[] = [
	'VA',
	'NNVA',
	'NVA_MOTION',
	'NVA_TRANSPORT',
	'NVA_WAITING',
	'NVA_SEARCH',
	'UNCERTAIN',
	'NO_PERSON'
];

export const ACTIVITY_LABEL: Record<string, string> = {
	working: 'Working',
	inspecting: 'Inspecting',
	walking: 'Walking',
	reaching: 'Reaching',
	carrying: 'Carrying',
	searching: 'Searching',
	waiting: 'Waiting',
	no_person: 'No person',
	uncertain: 'Unclear'
};

export const activityLabel = (activity: string) =>
	ACTIVITY_LABEL[activity] ??
	activity.charAt(0).toUpperCase() + activity.slice(1).replace(/_/g, ' ');

export const isWaste = (category: string) => category.startsWith('NVA_');

/** Timeline frames whose second falls in [start, end). */
export function framesIn(frames: TimelineFrame[], start: number, end: number): TimelineFrame[] {
	return frames.filter((f) => f.timestamp >= start && f.timestamp < end);
}
