// Thumbnails cut from the loaded video in the browser, for incidents the backend sent no snapshot for
// (for example after moving a threshold). Captures run one at a time on a hidden video element.
const cache = new Map<string, string>();
let queue: Promise<unknown> = Promise.resolve();
const videos = new Map<string, HTMLVideoElement>();

function videoFor(url: string): Promise<HTMLVideoElement> {
	const existing = videos.get(url);
	if (existing)
		return existing.readyState >= 1
			? Promise.resolve(existing)
			: once(existing, 'loadedmetadata').then(() => existing);
	const video = document.createElement('video');
	video.muted = true;
	video.preload = 'auto';
	video.playsInline = true;
	video.src = url;
	videos.set(url, video);
	return once(video, 'loadedmetadata').then(() => video);
}

function once(target: HTMLVideoElement, event: string): Promise<void> {
	return new Promise((resolve, reject) => {
		const ok = () => (target.removeEventListener('error', fail), resolve());
		const fail = () => (target.removeEventListener(event, ok), reject(new Error('video error')));
		target.addEventListener(event, ok, { once: true });
		target.addEventListener('error', fail, { once: true });
	});
}

/** A small JPEG data URI of the frame at `time`, or null when it cannot be read. */
export function captureFrame(url: string, time: number, width = 320): Promise<string | null> {
	const key = `${url}@${time.toFixed(2)}`;
	const hit = cache.get(key);
	if (hit) return Promise.resolve(hit);

	const job = queue.then(async () => {
		try {
			const video = await videoFor(url);
			video.currentTime = Math.min(Math.max(0, time), Math.max(0, video.duration - 0.05));
			await once(video, 'seeked');
			const canvas = document.createElement('canvas');
			canvas.width = width;
			canvas.height =
				Math.round((width * video.videoHeight) / video.videoWidth) || Math.round(width * 0.5625);
			canvas.getContext('2d')?.drawImage(video, 0, 0, canvas.width, canvas.height);
			const data = canvas.toDataURL('image/jpeg', 0.7);
			cache.set(key, data);
			return data;
		} catch {
			return null;
		}
	});
	queue = job.catch(() => null);
	return job;
}

/** Forget the hidden video of a source that is gone (an upload's object URL). */
export function releaseVideo(url: string) {
	videos.get(url)?.removeAttribute('src');
	videos.delete(url);
	for (const key of [...cache.keys()]) if (key.startsWith(`${url}@`)) cache.delete(key);
}
