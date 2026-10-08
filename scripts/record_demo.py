"""Record a demo video of StoryWeaver by itself: a hidden Edge/Chrome tours the app and plays three requests while
the screen and the app's own sound (narration, music, effects) are captured; a short spoken voice-over introduces the
quiet parts (the home screen, a refusal, the in-app explanation), and ffmpeg joins it all.

    uv run storyweaver --port 8020 --no-browser          # in one terminal
    uv run python scripts/record_demo.py                  # in another terminal

It writes demo/storyweaver_demo.mp4 and a short preview, docs/images/demo.gif.

Needs ffmpeg (on PATH, or ``pip install imageio-ffmpeg``) and Microsoft Edge or Google Chrome.
The spoken wish is a real voice clip (made with the neural voices) fed to the browser as its microphone.
"""

from __future__ import annotations

import argparse
import asyncio
import base64
import json
import re
import shutil
import subprocess
import sys
import tempfile
import time
import urllib.request
from pathlib import Path

import websockets

ROOT = Path(__file__).resolve().parents[1]
BROWSERS = [r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
            r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
            r"C:\Program Files\Google\Chrome\Application\chrome.exe",
            "/usr/bin/google-chrome", "/usr/bin/microsoft-edge",
            "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"]
WISH = "Please add a friendly firefly who glows like a little lantern!"
PRESENTER = "en-US-AndrewNeural"
VOICEOVER = {
    "intro": "This is StoryWeaver, an immersive storytelling agent. Type or say an idea, choose who is listening "
             "and how long you have, then pick the voices. A crew of A.I. agents does the rest.",
    "story": "Let's ask for a two-minute story for little ones.",
    "second": "Now a one-minute story for grown-ups, and a look behind the curtain.",
    "refusal": "Requests that aren't suitable never reach the storyteller. StoryWeaver explains why, "
               "and offers safe ideas instead.",
    "how": "Everything is explained inside the app: the crew of ten agents, how a story flows, the four safety "
           "layers, every design decision, and the measured results.",
}

# Everything a story plays goes through its AudioContext into the destination (each story opens a new context):
# tap every context into its own MediaRecorder, remembering when it started. Lines spoken by the browser's own voice
# (the fallback when a neural line is late) cannot be recorded, so they are counted.
TAP_AUDIO = """
(() => {
  const connect = AudioNode.prototype.connect;
  const close = AudioContext.prototype.close;
  window.__tap = [];
  window.__deviceLines = 0;
  const speak = speechSynthesis.speak.bind(speechSynthesis);
  window.__deviceTexts = [];
  speechSynthesis.speak = (u) => { window.__deviceLines += 1; window.__deviceTexts.push(u.text); return speak(u); };
  AudioNode.prototype.connect = function (target, ...rest) {
    const out = connect.call(this, target, ...rest);
    if (target instanceof AudioDestinationNode && !this.context.__tapped) {
      this.context.__tapped = true;
      const dest = this.context.createMediaStreamDestination();
      connect.call(this, dest);
      const part = { ctx: this.context, start: Date.now() / 1000, chunks: [] };
      part.rec = new MediaRecorder(dest.stream, { mimeType: "audio/webm;codecs=opus", audioBitsPerSecond: 128000 });
      part.rec.ondataavailable = (e) => e.data.size && part.chunks.push(e.data);
      part.done = new Promise((r) => { part.rec.onstop = r; });
      part.rec.start(1000);
      window.__tap.push(part);
    }
    return out;
  };
  AudioContext.prototype.close = function () {
    const part = window.__tap.find((p) => p.ctx === this);
    if (part && part.rec.state !== "inactive") part.rec.stop();
    return close.call(this);
  };
  // glide the scrollable area that holds `sel` so that `to` (a selector, "top" or "bottom") is in view
  window.__glide = (sel, to, ms) => new Promise((done) => {
    let box = document.querySelector(sel);
    while (box && !(box.scrollHeight > box.clientHeight + 4 && /(auto|scroll)/.test(getComputedStyle(box).overflowY)))
      box = box.parentElement;
    box = box || document.scrollingElement;
    const from = box.scrollTop;
    const max = box.scrollHeight - box.clientHeight;
    const goal = to === "top" ? 0 : to === "bottom" ? max : Math.min(max, Math.max(0,
      document.querySelector(to).getBoundingClientRect().top - box.getBoundingClientRect().top + from - 28));
    box.style.scrollBehavior = "auto";
    const t0 = performance.now();
    const step = (now) => {
      const k = Math.min(1, (now - t0) / ms);
      const e = k < 0.5 ? 2 * k * k : 1 - Math.pow(-2 * k + 2, 2) / 2;
      box.scrollTop = from + (goal - from) * e;
      if (k < 1) requestAnimationFrame(step); else done(true);
    };
    requestAnimationFrame(step);
  });
})();
"""


def find_ffmpeg(explicit: str | None) -> str:
    if explicit:
        return explicit
    if shutil.which("ffmpeg"):
        return "ffmpeg"
    try:
        import imageio_ffmpeg
        return imageio_ffmpeg.get_ffmpeg_exe()
    except ImportError:
        sys.exit("ffmpeg not found: install it, or `pip install imageio-ffmpeg`, or pass --ffmpeg")


def seconds(ffmpeg: str, path: Path) -> float:
    info = subprocess.run([ffmpeg, "-i", str(path)], capture_output=True, text=True).stderr
    h, m, s = re.search(r"Duration: (\d+):(\d+):([\d.]+)", info).groups()
    return int(h) * 3600 + int(m) * 60 + float(s)


async def make_clips(ffmpeg: str, folder: Path) -> tuple[Path, dict[str, tuple[Path, float]]]:
    import edge_tts

    mp3 = folder / "wish.mp3"
    await edge_tts.Communicate(WISH, "en-US-AnaNeural", rate="-5%").save(str(mp3))
    wav = folder / "wish.wav"
    # Chrome loops a fake-microphone file: pad it with silence so the loop is quiet after the sentence
    subprocess.run([ffmpeg, "-y", "-loglevel", "error", "-i", str(mp3), "-af", "apad=pad_dur=30", "-ar", "48000",
                    "-ac", "1", "-c:a", "pcm_s16le", str(wav)], check=True)
    clips = {}
    for name, text in VOICEOVER.items():
        path = folder / f"vo_{name}.mp3"
        await edge_tts.Communicate(text, PRESENTER, rate="+4%").save(str(path))
        clips[name] = (path, seconds(ffmpeg, path))
    return wav, clips


class Page:
    def __init__(self, ws):
        self.ws, self.n, self.pending, self.frames = ws, 0, {}, []

    async def reader(self, frames_dir: Path):
        async for raw in self.ws:
            m = json.loads(raw)
            if m.get("id") in self.pending:
                self.pending.pop(m["id"]).set_result(m)
            elif m.get("method") == "Page.screencastFrame":
                p = m["params"]
                path = frames_dir / f"{len(self.frames):06d}.jpg"
                path.write_bytes(base64.b64decode(p["data"]))
                self.frames.append((time.time(), path))  # the same clock as the audio's start times
                await self.ws.send(json.dumps({"id": 10**9 + len(self.frames), "method": "Page.screencastFrameAck",
                                               "params": {"sessionId": p["sessionId"]}}))
            elif m.get("method") == "Runtime.exceptionThrown":
                error = m["params"]["exceptionDetails"].get("exception", {}).get("description", "")
                print("  page error:", error[:200])

    async def cdp(self, method, **params):
        self.n += 1
        fut = asyncio.get_running_loop().create_future()
        self.pending[self.n] = fut
        await self.ws.send(json.dumps({"id": self.n, "method": method, "params": params}))
        return (await asyncio.wait_for(fut, 120)).get("result", {})

    async def js(self, expr):
        r = await self.cdp("Runtime.evaluate", expression=expr, awaitPromise=True, returnByValue=True)
        return r.get("result", {}).get("value")

    async def until(self, expr, timeout=60.0) -> bool:
        t0 = time.time()
        while time.time() - t0 < timeout:
            if await self.js(expr):
                return True
            await asyncio.sleep(0.25)
        print("  (timed out waiting for", expr[:70] + ")")
        return False

    async def type(self, selector, text, delay=0.02):
        await self.js(f"document.querySelector('{selector}').value = ''; 1")
        for i in range(1, len(text) + 1):
            await self.js(f"(() => {{ const el = document.querySelector('{selector}');"
                          f" el.value = {json.dumps(text[:i])}; el.dispatchEvent(new Event('input')); return 1; }})()")
            await asyncio.sleep(delay)

    async def click(self, selector):
        await self.js(f"document.querySelector({json.dumps(selector)})?.click(); 1")

    async def glide(self, inside, to, ms=1800):
        await self.js(f"window.__glide({json.dumps(inside)}, {json.dumps(to)}, {ms})")

    async def key(self, kind):
        event = f"new KeyboardEvent('{kind}', {{code: 'Space', key: ' ', bubbles: true}})"
        await self.js(f"document.body.dispatchEvent({event}); 1")

    async def view(self) -> str:
        return await self.js("document.body.dataset.view")


async def wait_for(page: Page, what: str, limit: float) -> bool:
    expr = {"end": "!document.querySelector('#endcard').hidden",
            "choice": "!document.querySelector('#choices').hidden",
            "no-choice": "document.querySelector('#choices').hidden"}[what]
    return await page.until(expr, limit)


async def story(page: Page, prompt: str, audience: str, minutes: int):
    await page.glide("#prompt", "top", 900)
    await page.type("#prompt", prompt)
    await asyncio.sleep(0.4)
    await page.click(f"#audience [data-value={audience}]")
    await asyncio.sleep(0.5)
    await page.click(f'#length [data-value="{minutes}"]')
    await page.js("document.querySelector('#engine').value = 'neural';"
                  "document.querySelector('#engine').dispatchEvent(new Event('change')); 1")
    await asyncio.sleep(1.0)
    await page.click("#begin")
    await page.until("document.body.dataset.view === 'stage'", 60)


async def run(args) -> int:
    ffmpeg = find_ffmpeg(args.ffmpeg)
    browser = args.browser or next((b for b in BROWSERS if Path(b).exists()), None)
    if not browser:
        sys.exit("No Edge or Chrome found: pass --browser")
    work = Path(tempfile.mkdtemp(prefix="storyweaver-demo-"))
    frames_dir = work / "frames"
    frames_dir.mkdir()
    wish, clips = await make_clips(ffmpeg, work)
    spoken: list[tuple[float, Path]] = []  # (when, clip): the presenter's voice-over, placed on the timeline later

    async def say(name: str, wait: bool = False):
        path, length = clips[name]
        spoken.append((time.time(), path))
        if wait:
            await asyncio.sleep(length + 0.3)
        return length

    port = 9361
    proc = subprocess.Popen([browser, "--headless=new", f"--remote-debugging-port={port}",
                             f"--user-data-dir={work / 'profile'}", "--autoplay-policy=no-user-gesture-required",
                             "--use-fake-ui-for-media-stream", "--use-fake-device-for-media-stream",
                             f"--use-file-for-fake-audio-capture={wish}", "--mute-audio", "--no-first-run",
                             "--hide-scrollbars", "about:blank"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    t_start = time.time()

    def mark(label: str):
        print(f"  {time.time() - t_start:6.1f}s  {label}", flush=True)

    try:
        for _ in range(80):
            try:
                targets = json.loads(urllib.request.urlopen(f"http://127.0.0.1:{port}/json").read())
                break
            except OSError:
                time.sleep(0.25)
        target = next(t for t in targets if t["type"] == "page")
        async with websockets.connect(target["webSocketDebuggerUrl"], max_size=200_000_000, ping_interval=None) as ws:
            page = Page(ws)
            reader = asyncio.create_task(page.reader(frames_dir))
            for method in ("Runtime.enable", "Page.enable"):
                await page.cdp(method)
            await page.cdp("Emulation.setDeviceMetricsOverride", width=1280, height=720, deviceScaleFactor=1,
                           mobile=False)
            await page.cdp("Page.addScriptToEvaluateOnNewDocument", source=TAP_AUDIO)
            await page.cdp("Page.navigate", url=args.url)
            await page.until("!document.querySelector('#begin').disabled && "
                             "document.querySelector('#status-line').textContent.includes('Agents')", 60)
            await page.cdp("Page.startScreencast", format="jpeg", quality=82, maxWidth=1280, maxHeight=720)
            t_start = time.time()

            print("0) the home screen and its options")
            await asyncio.sleep(1.0)
            length = await say("intro")
            await asyncio.sleep(1.5)
            await page.glide("#home", "#audience", 2200)
            await asyncio.sleep(1.2)
            await page.glide("#home", "#length", 1800)
            await page.click('#length [data-value="3"]')
            await asyncio.sleep(0.8)
            await page.click('#length [data-value="1"]')
            await asyncio.sleep(0.8)
            await page.glide("#home", "#engine", 1800)
            await asyncio.sleep(1.0)
            await page.glide("#home", "bottom", 2000)
            await asyncio.sleep(max(1.0, length - 10.5))
            await page.glide("#home", "top", 1800)
            mark("home tour done")

            print("1) a 2-minute story for little ones, with a spoken wish and a choice")
            await say("story")  # the presenter speaks while the idea is typed
            await story(page, "A little hedgehog who is afraid of the dark", "kids", 2)
            mark("story 1 on stage")
            await page.until("document.querySelector('#chapter-label').textContent.startsWith('Chapter')", 90)
            await asyncio.sleep(args.wish_after)  # a few sentences into the first part: the change is heard at once
            await page.key("keydown")
            await asyncio.sleep(4.6)  # the clip is ~3.5 s
            await page.key("keyup")
            mark("wish spoken")
            if await wait_for(page, "choice", 150):
                mark("choice shown")
                await asyncio.sleep(4.0)
                await page.click("#choice-cards button")
                await wait_for(page, "no-choice", 20)
            await wait_for(page, "end", 170)
            mark("story 1 ended")
            await asyncio.sleep(6.0)  # the end card

            print("2) a 1-minute story for grown-ups, with a look behind the curtain")
            await page.click("#again-btn")
            await page.until("document.body.dataset.view === 'home'", 10)
            await asyncio.sleep(0.8)
            await say("second")
            await story(page, "A lighthouse keeper who receives letters from the future", "adults", 1)
            mark("story 2 on stage")
            await asyncio.sleep(16)
            await page.click("#crew-btn")
            for tab in ("crew", "log", "safety", "bible", "numbers"):
                await page.click(f".drawer .tabs [data-tab={tab}]")
                await asyncio.sleep(3.2)
            await page.click("#drawer-close")
            mark("drawer shown")
            await wait_for(page, "end", 75)
            mark("story 2 ended")
            await asyncio.sleep(5.0)

            print("3) a request that is refused, kindly")
            await page.click("#again-btn")
            await page.until("document.body.dataset.view === 'home'", 10)
            await asyncio.sleep(0.8)
            await page.glide("#prompt", "top", 600)
            await page.click("#audience [data-value=kids]")
            await page.type("#prompt", "How to make a real bomb at home")
            await asyncio.sleep(0.6)
            await page.click("#begin")
            await page.until("!document.querySelector('#refusal').hidden", 40)
            mark(f"refusal shown (view: {await page.view()})")
            await asyncio.sleep(2.0)
            await say("refusal", wait=True)
            await asyncio.sleep(1.0)

            print("4) how it works, inside the app")
            await page.click("#refusal-back")
            await page.until("document.body.dataset.view === 'home'", 10)
            await page.click("#home [data-open=how]")
            await asyncio.sleep(1.5)
            length = await say("how")
            for section, pause in (("#hiw-crew", 2.5), ("#hiw-diagram", 4.0), ("#hiw-safety", 3.0),
                                   ("#hiw-decisions", 3.0), ("#hiw-metrics", 3.5)):
                await page.glide("#hiw-crew", section, 1600)
                await asyncio.sleep(pause)
            await page.glide("#hiw-crew", "bottom", 1500)
            await asyncio.sleep(2.5)
            mark("how it works shown")

            await page.cdp("Page.stopScreencast")
            t_end = time.time()
            device_lines = await page.js("window.__deviceLines")
            audio = await page.js("""Promise.all(window.__tap.map(async (part) => {
                if (part.rec.state !== 'inactive') part.rec.stop();
                await part.done;
                const blob = new Blob(part.chunks, { type: 'audio/webm' });
                const data = await new Promise((r) => { const f = new FileReader();
                  f.onload = () => r(f.result.split(',')[1]); f.readAsDataURL(blob); });
                return { start: part.start, data };
            }))""")
            reader.cancel()
    finally:
        proc.terminate()

    print(f"captured {len(page.frames)} frames over {t_end - t_start:.0f} s; "
          f"lines spoken by the browser's fallback voice (not in the recording): {device_lines}")
    if not page.frames or not audio:
        sys.exit("nothing captured")
    first = page.frames[0][0]
    concat = work / "frames.txt"
    with concat.open("w", encoding="utf-8") as f:  # each frame lasts until the next; the last one until the end
        for (ts, path), nxt in zip(page.frames, [*(t for t, _ in page.frames[1:]), t_end], strict=True):
            f.write(f"file '{path.as_posix()}'\nduration {max(0.001, nxt - ts):.3f}\n")
        f.write(f"file '{page.frames[-1][1].as_posix()}'\n")

    inputs, chains = [], []
    tracks = [(part["start"], work / f"audio{i}.webm", part["data"]) for i, part in enumerate(audio)]
    tracks += [(when, path, None) for when, path in spoken]
    for i, (start, path, data) in enumerate(tracks, 1):  # every recording and voice-over, placed where it began
        if data:
            path.write_bytes(base64.b64decode(data))
        inputs += ["-i", str(path)]
        delay = max(0, round((start - first) * 1000))
        gain = "" if data else ",volume=1.15"
        chains.append(f"[{i}:a]aresample=48000,adelay={delay}:all=1{gain}[a{i}]")
    mix = "".join(f"[a{i}]" for i in range(1, len(tracks) + 1))
    graph = ";".join(chains) + f";{mix}amix=inputs={len(tracks)}:normalize=0:duration=longest[a]"
    out = ROOT / "demo" / "storyweaver_demo.mp4"
    out.parent.mkdir(exist_ok=True)
    subprocess.run([ffmpeg, "-y", "-loglevel", "error", "-f", "concat", "-safe", "0", "-i", str(concat), *inputs,
                    "-filter_complex", graph, "-map", "0:v", "-map", "[a]", "-vf", "fps=25,format=yuv420p",
                    "-c:v", "libx264", "-preset", "slow", "-crf", "33", "-c:a", "aac", "-b:a", "96k",
                    "-t", f"{t_end - first:.2f}", "-movflags", "+faststart", str(out)], check=True)
    print(f"wrote {out.relative_to(ROOT)} ({out.stat().st_size / 1e6:.1f} MB, {t_end - first:.0f} s)")

    # a short silent preview for the README: the crew assembling and the story beginning
    gif = ROOT / "docs" / "images" / "demo.gif"
    subprocess.run([ffmpeg, "-y", "-loglevel", "error", "-ss", f"{args.gif_from:.1f}", "-t", f"{args.gif_seconds:.1f}",
                    "-i", str(out), "-vf", "fps=8,scale=720:-1:flags=lanczos,split[a][b];"
                    "[a]palettegen=max_colors=128[p];[b][p]paletteuse=dither=bayer:bayer_scale=4", str(gif)],
                   check=True)
    print(f"wrote {gif.relative_to(ROOT)} ({gif.stat().st_size / 1e6:.1f} MB)")
    shutil.rmtree(work, ignore_errors=True)
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--url", default="http://127.0.0.1:8020/")
    parser.add_argument("--browser")
    parser.add_argument("--ffmpeg")
    parser.add_argument("--wish-after", type=float, default=4.0,
                        help="seconds into story 1's first part before the spoken wish")
    parser.add_argument("--gif-from", type=float, default=19.0, help="where the README preview starts (seconds)")
    parser.add_argument("--gif-seconds", type=float, default=16.0)
    return asyncio.run(run(parser.parse_args()))


if __name__ == "__main__":
    sys.exit(main())
