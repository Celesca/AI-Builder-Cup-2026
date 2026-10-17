// The video position shared by every page: whichever player is mounted reports its time here and
// obeys seek requests, so any timestamp in the app can jump the video.
class Playback {
	time = $state(0);
	duration = $state(0);
	request = $state<{ t: number; play: boolean; n: number } | null>(null);
	/** The floating video starts collapsed and opens when a moment is played */
	dockCollapsed = $state(true);
	private n = 0;

	seek(t: number, play = true) {
		this.time = t;
		this.request = { t, play, n: ++this.n };
		this.dockCollapsed = false;
	}
}

export const playback = new Playback();
