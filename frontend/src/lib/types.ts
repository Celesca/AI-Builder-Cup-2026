// Shapes of ai_backend's POST /analysis/analyze/upload response (only the fields the dashboard reads),
// plus the dashboard's own types. The source of truth is ai_backend/openapi.json.

export type Level = 'low' | 'medium' | 'high';
export type Language = 'en' | 'th' | 'ja';
export type Decision = 'approved' | 'deferred' | 'rejected';

/** Muda categories produced by the Safety Agent. */
export type Category =
	| 'VA'
	| 'NNVA'
	| 'NVA_MOTION'
	| 'NVA_TRANSPORT'
	| 'NVA_WAITING'
	| 'NVA_SEARCH'
	| 'NO_PERSON'
	| 'UNCERTAIN';

export interface RuleOut {
	id: string;
	prompt: string;
	severity: Level;
	threshold: number;
}

export interface TimelineFrame {
	timestamp: number;
	frame_idx: number;
	activity: string;
	category: Category;
	confidence: number;
	/** P(violation) per rule id, 0-1 */
	rule_confidences: Record<string, number>;
}

export interface BackendEvent {
	rule_id: string;
	prompt: string;
	severity: Level;
	start_time: number;
	end_time: number;
	duration: number;
	peak_confidence: number;
	mean_confidence: number;
	frame_count: number;
	key_frame_idx: number;
	key_timestamp: number;
	description: string;
	snapshot: string | null;
}

export interface ActivitySegment {
	start_time: number;
	end_time: number;
	duration: number;
	activity: string;
	category: Category;
	confidence: number;
	frame_count: number;
	key_timestamp: number;
	description: string;
	snapshot: string | null;
}

export interface LssCard {
	id: string;
	title: string;
	category: string;
	priority: Level;
	observation: string;
	evidence: { start_time: number; end_time: number; note: string }[];
	root_cause: string;
	recommendation: string;
	kb_card_ids: string[];
	est_seconds_saved_per_cycle: number | null;
	waste_share_removed: number | null;
	confidence: number;
	roi: {
		hours_saved_per_shift: number;
		throughput_gain_percent: number | null;
		basis: string;
	} | null;
}

export interface WasteMetric {
	category: string;
	label: string;
	seconds: number;
	percent_of_person_time: number;
	projected_hours_per_shift: number;
}

export interface StationContext {
	station_name: string;
	process_description: string;
	takt_time_s: number | null;
	cycle_time_s: number | null;
	cycles_per_shift: number | null;
	shift_hours: number;
	operators: number;
	language: Language;
	notes: string;
}

export interface AnalysisResponse {
	success: boolean;
	video_path: string | null;
	safety: {
		job_id: string;
		model: string;
		video_duration: number;
		sample_fps: number;
		vlm_usage: Record<string, number> | null;
		rules: RuleOut[];
		stats: { frames_analyzed: number; safety_events: number; frames_with_violation: number };
		safety_events: BackendEvent[];
		activity: {
			summary: {
				observed_seconds: number;
				person_visible_seconds: number;
				by_activity_seconds: Record<string, number>;
				by_category_seconds: Record<string, number>;
				va_percent: number;
				nnva_percent: number;
				nva_percent: number;
				uncertain_percent: number;
			};
			segments: ActivitySegment[];
			timeline: TimelineFrame[];
		};
	};
	person_count: {
		statistics: {
			max_persons: number;
			avg_persons: number;
			frames_with_people: number;
			frames_analyzed: number;
		};
		timeline: { timestamps: number[]; counts: number[] };
	} | null;
	person_count_error: string | null;
	lss: {
		job_id: string;
		source: 'llm' | 'rules';
		model: string | null;
		llm_error: string | null;
		context: StationContext;
		metrics: {
			video_duration: number;
			va_percent: number;
			nnva_percent: number;
			nva_percent: number;
			uncertain_percent: number;
			waste_by_category: WasteMetric[];
			projected_nva_hours_per_shift: number;
			cycles_per_shift: number | null;
		};
		summary: string;
		lss_cards: LssCard[];
		safety_actions: { rule_id: string; severity: Level; action: string; kb_card_ids: string[] }[];
		operator_questions: { timestamp: number; question: string }[];
		knowledge_cards_used: { id: string; title: string; source: string }[];
		usage: Record<string, number> | null;
	};
	/** Present on bundled demo results only */
	demo?: { synthetic: boolean; note: string };
}

// ---- dashboard types ------------------------------------------------------------------------------------------

/** A safety rule as the manager edits it. */
export interface Rule {
	id: string;
	label: string;
	prompt: string;
	severity: Level;
	threshold: number;
	enabled: boolean;
}

/** An incident derived from the per-frame confidences with the rules as they are now. */
export interface Incident {
	key: string;
	ruleId: string;
	label: string;
	severity: Level;
	start: number;
	end: number;
	duration: number;
	peak: number;
	mean: number;
	frames: number;
	keyTime: number;
	prompt: string;
	description: string;
	snapshot: string | null;
}

export interface DemoClip {
	id: string;
	title: string;
	video: string;
	analysis: string;
	duration: number;
	synthetic?: boolean;
	note?: string;
	/** Optional pre-made copy with boxes drawn (POST /safety/annotate), drawn with the default rules */
	annotated?: string;
}

export interface SourceInfo {
	kind: 'demo' | 'upload';
	id: string;
	name: string;
	/** Object URL (upload) or static path (demo); null when an upload was restored without its file */
	url: string | null;
	file: File | null;
	synthetic: boolean;
	/** Bytes of an uploaded file, to tell a re-chosen file from another one with the same name */
	size?: number;
}

export interface BackendStatus {
	state: 'checking' | 'online' | 'offline';
	keyConfigured: boolean;
	vlmModel: string | null;
	llmModel: string | null;
	detail: string;
}

// ---- voice agent ------------------------------------------------------------------------------------------------

export interface VoiceStatus {
	elevenlabs_configured: boolean;
	llm_configured: boolean;
	llm_model: string;
	tts_model: string;
	voice_id: string;
	audio_cache: { clips: number; bytes: number; replays: number };
}

export interface VoiceSource {
	id: string;
	title: string;
	source: 'analysis' | 'knowledge';
}

/** How a message was last spoken: ElevenLabs (new or from the voice database) or the browser's own voice. */
export type VoiceEngine = 'elevenlabs' | 'database' | 'browser';

export interface ChatMessage {
	id: string;
	role: 'user' | 'assistant';
	text: string;
	sources?: VoiceSource[];
	/** llm, or retrieval when the backend has no OpenRouter key */
	answeredBy?: 'llm' | 'retrieval' | 'greeting';
	model?: string | null;
	engine?: VoiceEngine;
}
