import { spawnSync } from "node:child_process";
import fs from "node:fs/promises";
import path from "node:path";
import { fileURLToPath } from "node:url";

const here = path.dirname(fileURLToPath(import.meta.url));
const root = path.resolve(here, "../..");
const envPath = path.join(root, ".env");
const work = path.join(here, "generated");
const sourceVideo = "C:\\Users\\Kurst\\Downloads\\TraceOS.mp4";
const outputVideo = "C:\\Users\\Kurst\\Downloads\\TraceOS_narrated.mp4";
const plan = JSON.parse(await fs.readFile(path.join(here, "narration-plan.json"), "utf8"));

function parseEnv(text) {
  return Object.fromEntries(text.split(/\r?\n/).map(line => line.trim()).filter(line => line && !line.startsWith("#") && line.includes("=")).map(line => {
    const index = line.indexOf("=");
    return [line.slice(0, index).trim(), line.slice(index + 1).trim().replace(/^['"]|['"]$/g, "")];
  }));
}

const localEnv = parseEnv(await fs.readFile(envPath, "utf8"));
const apiKey = process.env.ELEVENLABS_API_KEY || localEnv.ELEVENLABS_API_KEY || localEnv.ELEVEN_LAB;
if (!apiKey) throw new Error("ELEVENLABS_API_KEY or ELEVEN_LAB is missing from the project .env file.");

const ffmpegCandidates = [
  path.join(root, "tools", "demo-recorder", "node_modules", "@ffmpeg-installer", "win32-x64", "ffmpeg.exe"),
  "ffmpeg",
];
const ffmpeg = ffmpegCandidates.find(candidate => candidate === "ffmpeg" || requireExists(candidate));
function requireExists(candidate) {
  try { return Boolean(requireStat(candidate)); } catch { return false; }
}
function requireStat(candidate) {
  return spawnSync("powershell", ["-NoProfile", "-Command", `[IO.File]::Exists('${candidate.replaceAll("'", "''")}')`], { encoding: "utf8" }).stdout.trim() === "True";
}

await fs.mkdir(work, { recursive: true });

async function apiJson(url, options = {}) {
  const response = await fetch(url, { ...options, headers: { "xi-api-key": apiKey, "Content-Type": "application/json", ...(options.headers || {}) } });
  if (!response.ok) throw new Error(`ElevenLabs ${response.status}: ${(await response.text()).slice(0, 500)}`);
  return response.json();
}

async function selectVoice() {
  const preferredSharedVoiceId = "qRUgOhnxGASxirG4fKjv";
  const accountQuery = new URLSearchParams({ page_size: "100", search: "TraceOS Narrator" });
  const accountVoices = await apiJson(`https://api.elevenlabs.io/v2/voices?${accountQuery}`);
  const existing = (accountVoices.voices || []).find(candidate => candidate.name === "TraceOS Narrator");
  if (existing) return existing;

  const libraryQuery = new URLSearchParams({
    page_size: "100",
    search: "David Energetic Deep Pleasant",
    gender: "male",
    age: "young",
  });
  const library = await apiJson(`https://api.elevenlabs.io/v1/shared-voices?${libraryQuery}`);
  const chosen = (library.voices || []).find(candidate => candidate.voice_id === preferredSharedVoiceId);
  if (!chosen?.public_owner_id) {
    throw new Error("The selected professional young male Mexican voice is no longer available in the ElevenLabs shared library.");
  }
  try {
    const added = await apiJson(`https://api.elevenlabs.io/v1/voices/add/${chosen.public_owner_id}/${chosen.voice_id}`, {
      method: "POST",
      body: JSON.stringify({ new_name: "TraceOS Narrator", bookmarked: true }),
    });
    return { ...chosen, voice_id: added.voice_id || chosen.voice_id, name: "TraceOS Narrator" };
  } catch (error) {
    const refreshed = await apiJson(`https://api.elevenlabs.io/v2/voices?${accountQuery}`);
    const recovered = (refreshed.voices || []).find(candidate => candidate.name === "TraceOS Narrator");
    if (recovered) return recovered;
    throw error;
  }
}

function wordsFromAlignment(alignment) {
  const characters = alignment.characters || [];
  const starts = alignment.character_start_times_seconds || [];
  const ends = alignment.character_end_times_seconds || [];
  const text = characters.join("");
  const words = [];
  for (const match of text.matchAll(/\S+/g)) {
    const first = match.index;
    const last = first + match[0].length - 1;
    words.push({ text: match[0], start: starts[first] ?? 0, end: ends[last] ?? starts[last] ?? 0 });
  }
  return words;
}

function assTime(seconds) {
  const cs = Math.max(0, Math.round(seconds * 100));
  const hours = Math.floor(cs / 360000);
  const minutes = Math.floor((cs % 360000) / 6000);
  const secs = Math.floor((cs % 6000) / 100);
  return `${hours}:${String(minutes).padStart(2, "0")}:${String(secs).padStart(2, "0")}.${String(cs % 100).padStart(2, "0")}`;
}

function assEscape(text) {
  return text.replaceAll("\\", "\\\\").replaceAll("{", "\\{").replaceAll("}", "\\}").replaceAll("\n", "\\N");
}

function subtitleEvents(segments) {
  const events = [];
  for (const segment of segments) {
    const words = segment.words.map(word => ({ ...word, start: word.start + segment.start, end: word.end + segment.start }));
    for (let offset = 0; offset < words.length; offset += 6) {
      const chunk = words.slice(offset, offset + 6);
      chunk.forEach((word, index) => {
        const next = chunk[index + 1];
        const end = next ? next.start : Math.max(word.end + 0.12, word.start + 0.18);
        const line = chunk.map((item, itemIndex) => itemIndex === index
          ? `{\\fs60\\b1\\c&H00B0D1D7&}${assEscape(item.text)}{\\rWordFocus}`
          : assEscape(item.text)).join(" ");
        events.push(`Dialogue: 0,${assTime(word.start)},${assTime(end)},WordFocus,,0,0,0,,${line}`);
      });
    }
  }
  return events;
}

const voice = await selectVoice();
await fs.writeFile(path.join(work, "voice-selection.json"), JSON.stringify({ voice_id: voice.voice_id, name: voice.name, category: voice.category, labels: voice.labels, description: voice.description }, null, 2));

const subtitlePath = path.join(work, "TraceOS-word-focus.ass");
const audioPaths = plan.segments.map((_, index) => path.join(work, `voice-${String(index + 1).padStart(2, "0")}.mp3`));
const generatedAssetsExist = await Promise.all([...audioPaths, subtitlePath].map(async asset => {
  try { await fs.access(asset); return true; } catch { return false; }
}));
const renderedSegments = [];
if (generatedAssetsExist.every(Boolean)) {
  renderedSegments.push(...plan.segments.map((segment, index) => ({ ...segment, audioPath: audioPaths[index] })));
} else {
  for (let index = 0; index < plan.segments.length; index += 1) {
    const segment = plan.segments[index];
    const response = await apiJson(`https://api.elevenlabs.io/v1/text-to-speech/${voice.voice_id}/with-timestamps?output_format=mp3_44100_128`, {
      method: "POST",
      body: JSON.stringify({
        text: segment.text,
        model_id: "eleven_multilingual_v2",
        voice_settings: { stability: 0.55, similarity_boost: 0.82, style: 0.18, use_speaker_boost: true, speed: 1.02 },
      }),
    });
    const audioPath = audioPaths[index];
    await fs.writeFile(audioPath, Buffer.from(response.audio_base64, "base64"));
    const alignment = response.normalized_alignment || response.alignment;
    if (!alignment) throw new Error(`No timing alignment returned for narration segment ${index + 1}`);
    renderedSegments.push({ ...segment, audioPath, words: wordsFromAlignment(alignment) });
  }

  const ass = `[Script Info]
ScriptType: v4.00+
PlayResX: 1920
PlayResY: 1080
ScaledBorderAndShadow: yes
WrapStyle: 2

[V4+ Styles]
Format: Name,Fontname,Fontsize,PrimaryColour,SecondaryColour,OutlineColour,BackColour,Bold,Italic,Underline,StrikeOut,ScaleX,ScaleY,Spacing,Angle,BorderStyle,Outline,Shadow,Alignment,MarginL,MarginR,MarginV,Encoding
Style: WordFocus,Arial,44,&H00FFFFFF,&H00FFFFFF,&H0011100F,&H9811100F,0,0,0,0,100,100,0,0,3,3,0,2,130,130,68,1

[Events]
Format: Layer,Start,End,Style,Name,MarginL,MarginR,MarginV,Effect,Text
${subtitleEvents(renderedSegments).join("\n")}
`;
  await fs.writeFile(subtitlePath, ass, "utf8");
}

const musicPath = path.join(work, "TraceOS-instrumental.mp3");
try { await fs.access(musicPath); } catch {
  const response = await fetch("https://api.elevenlabs.io/v1/music?output_format=mp3_44100_128", {
    method: "POST",
    headers: { "xi-api-key": apiKey, "Content-Type": "application/json" },
    body: JSON.stringify({
      prompt: "Epic instrumental guardian theme for a polished enterprise cybersecurity product demo: the feeling of a powerful protector standing watch over critical systems. Heroic low strings, warm brass swells, deep controlled cinematic percussion, a modern electronic pulse, subtle rising tension, and a confident protective resolution. Serious, vigilant, trustworthy, and emotionally uplifting without becoming bombastic. Leave spacious passages for narration and build stronger energy between spoken sections. No vocals, no speech, no choir, no logos, and no recognizable existing melody.",
      music_length_ms: 90000,
      model_id: "music_v1",
      force_instrumental: true,
    }),
  });
  if (!response.ok) throw new Error(`ElevenLabs music ${response.status}: ${(await response.text()).slice(0, 500)}`);
  await fs.writeFile(musicPath, Buffer.from(await response.arrayBuffer()));
}

const musicLoopPath = path.join(work, "TraceOS-instrumental-loop.mp3");
try { await fs.access(musicLoopPath); } catch {
  const trim = spawnSync(ffmpeg, [
    "-hide_banner", "-y", "-i", musicPath, "-t", "78",
    "-c:a", "libmp3lame", "-b:a", "128k", musicLoopPath,
  ], { stdio: "inherit" });
  if (trim.status !== 0) throw new Error(`music loop preparation failed with exit code ${trim.status}`);
}

const inputs = ["-i", sourceVideo, "-stream_loop", "-1", "-i", musicLoopPath];
for (const segment of renderedSegments) inputs.push("-i", segment.audioPath);
const narrationFilters = renderedSegments.map((segment, index) => {
  const delay = Math.round(segment.start * 1000);
  return `[${index + 2}:a]aformat=sample_rates=48000:channel_layouts=stereo,adelay=${delay}|${delay}[v${index}]`;
});
const narrationInputs = renderedSegments.map((_, index) => `[v${index}]`).join("");
const filter = [
  ...narrationFilters,
  `${narrationInputs}amix=inputs=${renderedSegments.length}:duration=longest,loudnorm=I=-16:TP=-1.5:LRA=7,asplit=2[voice_sc][voice_mix]`,
  `[1:a]atrim=0:${plan.video_duration_seconds},asetpts=PTS-STARTPTS,volume=0.32[music]`,
  `[music][voice_sc]sidechaincompress=threshold=0.015:ratio=12:attack=12:release=650[ducked]`,
  `[ducked][voice_mix]amix=inputs=2:duration=first,volume=2,alimiter=limit=0.95[aout]`,
].join(";");

const assFilterPath = subtitlePath.replaceAll("\\", "/").replace(/^([A-Za-z]):/, "$1\\:").replaceAll("'", "\\'");
const args = [
  "-hide_banner", "-y", ...inputs,
  "-filter_complex", filter,
  "-vf", `ass='${assFilterPath}'`,
  "-map", "0:v:0", "-map", "[aout]",
  "-t", String(plan.video_duration_seconds),
  "-c:v", "libx264", "-preset", "medium", "-crf", "18", "-pix_fmt", "yuv420p",
  "-c:a", "aac", "-b:a", "192k", "-ar", "48000",
  "-movflags", "+faststart",
  "-metadata", "title=TraceOS - Agentic Forensics Demo",
  outputVideo,
];
const render = spawnSync(ffmpeg, args, { stdio: "inherit" });
if (render.status !== 0) throw new Error(`ffmpeg render failed with exit code ${render.status}`);
console.log(outputVideo);
