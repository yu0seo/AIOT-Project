// No external packages: platform admin credentials stay inside this Edge Function.
const BUCKET = "breathing-video";
const FPS = 10, SEGMENT = 2, RETENTION = 180, COUNT = 15;
class ApiError extends Error {
  constructor(status, message) { super(message); this.status = status; }
}
const json = (data, status = 200) => new Response(JSON.stringify(data), {
  status, headers: { "content-type": "application/json", "cache-control": "no-store" },
});
const pathPart = (value) => value.split("/").map(encodeURIComponent).join("/");
export async function digest(value) {
  return Array.from(new Uint8Array(await crypto.subtle.digest("SHA-256", new TextEncoder().encode(value))))
    .map((b) => b.toString(16).padStart(2, "0")).join("");
}
export function equal(a, b) {
  if (typeof a !== "string" || typeof b !== "string" || a.length !== b.length) return false;
  let value = 0;
  for (let i = 0; i < a.length; i++) value |= a.charCodeAt(i) ^ b.charCodeAt(i);
  return value === 0;
}
export function validateWindow(rows, now = Date.now()) {
  if (rows.length !== COUNT) throw new ApiError(409, "Waiting for 15 complete segments / 30 seconds.");
  if (now - Date.parse(rows.at(-1).capture_end) > 10000)
    throw new ApiError(409, "Camera video is stale.");
  if (Date.parse(rows.at(-1).capture_end) > now + 5000)
    throw new ApiError(409, "Capture timestamps are in the future.");
  for (let i = 1; i < rows.length; i++) {
    if (Number(rows[i].sequence) !== Number(rows[i-1].sequence) + 1 ||
        Math.abs(Date.parse(rows[i].capture_start) - Date.parse(rows[i-1].capture_end)) > 20)
      throw new ApiError(409, "The latest 30 seconds contain a gap or overlap.");
  }
  return rows;
}

export function createHandler(env, fetcher = fetch) {
  const base = env("SUPABASE_URL");
  const secrets = JSON.parse(env("SUPABASE_SECRET_KEYS") || "{}");
  const key = secrets.default || env("SUPABASE_SERVICE_ROLE_KEY");
  if (!base || !key) throw new Error("Supabase server credentials are missing.");
  const headers = { apikey: key, "content-type": "application/json" };
  if (!key.startsWith("sb_secret_")) headers.authorization = `Bearer ${key}`;

  async function remote(path, options = {}) {
    const response = await fetcher(base + path, { ...options,
      headers: { ...headers, ...options.headers } });
    const text = await response.text();
    let data;
    try { data = text ? JSON.parse(text) : null; } catch { data = null; }
    if (!response.ok) {
      // Do not log credentials, signed URLs, payloads, or full upstream responses.
      const error = new ApiError(502, "Supabase operation failed.");
      error.upstreamStatus = response.status;
      throw error;
    }
    return data;
  }
  async function rows(table, query = {}) {
    return await remote(`/rest/v1/${table}?${new URLSearchParams(query)}`);
  }
  async function authenticate(req, cameraId, mode) {
    if (!/^[A-Za-z0-9_-]{1,64}$/.test(cameraId || "")) throw new ApiError(400, "Invalid camera ID.");
    const token = req.headers.get("x-device-key") || "";
    if (token.length < 32 || token.length > 200) throw new ApiError(401, "Invalid device key.");
    const devices = await rows("breathing_video_devices", { camera_id: `eq.${cameraId}`, select: "*" });
    const device = devices?.[0];
    if (!device || !equal(await digest(token), device[mode + "_key_hash"]))
      throw new ApiError(401, "Invalid device key.");
    return device;
  }
  async function cleanupAuth(req) {
    const token = req.headers.get("x-cleanup-key") || "";
    if (token.length < 32 || token.length > 200) throw new ApiError(401, "Invalid cleanup key.");
    const settings = await rows("breathing_video_settings", { key: "eq.cleanup_key_hash", select: "value" });
    if (!equal(await digest(token), settings?.[0]?.value)) throw new ApiError(401, "Invalid cleanup key.");
  }
  async function signedUpload(path) {
    const data = await remote(`/storage/v1/object/upload/sign/${BUCKET}/${pathPart(path)}`, {
      method: "POST", headers: { "x-upsert": "false" }, body: "{}",
    });
    if (typeof data?.url !== "string" || !data.url.startsWith("/object/"))
      throw new ApiError(502, "Storage did not return an upload URL.");
    return base + "/storage/v1" + data.url;
  }
  async function signedDownload(path) {
    const data = await remote(`/storage/v1/object/sign/${BUCKET}/${pathPart(path)}`, {
      method: "POST", body: JSON.stringify({ expiresIn: 60 }),
    });
    const relative = data.signedURL || data.signedUrl;
    if (typeof relative !== "string" || !relative.startsWith("/object/"))
      throw new ApiError(502, "Storage did not return a download URL.");
    return base + "/storage/v1" + relative;
  }
  async function provision() {
    const buckets = await remote("/storage/v1/bucket");
    if (!buckets.some((bucket) => bucket.id === BUCKET)) {
      await remote("/storage/v1/bucket", { method: "POST", body: JSON.stringify({
        id: BUCKET, name: BUCKET, public: false, file_size_limit: 8388608,
        allowed_mime_types: ["video/mp2t"],
      }) });
    } else if (buckets.find((bucket) => bucket.id === BUCKET).public) {
      throw new ApiError(409, "The video bucket must be private.");
    }
    return { bucket: BUCKET, private: true };
  }
  async function cleanup() {
    const expired = await rows("breathing_video_expired_objects", { select: "object_path", limit: "1000" });
    if (expired.length) {
      await remote(`/storage/v1/object/${BUCKET}`, { method: "DELETE",
        body: JSON.stringify({ prefixes: expired.map((row) => row.object_path) }) });
    }
    // Remove metadata only once object removal succeeded; failed deletes are retried.
    // The anti-join prevents losing the index of an object beyond this batch's 1000 limit.
    const remaining = await rows("breathing_video_expired_objects", { select: "object_path", limit: "1" });
    if (!remaining.length) {
      await remote(`/rest/v1/breathing_video_segments?expires_at=lte.${encodeURIComponent(new Date().toISOString())}`,
        { method: "DELETE" });
    }
    return { removed_objects: expired.length, more: remaining.length > 0 };
  }
  return async function handle(req) {
    try {
      const url = new URL(req.url);
      const action = url.pathname.split("/").filter(Boolean).at(-1);
      if (action === "health" && req.method === "GET")
        return json({ service: "aiot-supabase-video", fps: FPS, retention_seconds: RETENTION,
          window_seconds: 30, server_time: new Date().toISOString() });
      if ((action === "provision" || action === "cleanup") && req.method === "POST") {
        await cleanupAuth(req);
        return json(action === "provision" ? await provision() : await cleanup());
      }
      if (action === "reserve" && req.method === "POST") {
        if (Number(req.headers.get("content-length") || 0) > 8192) throw new ApiError(413, "Request too large.");
        const reader = req.body?.getReader();
        const chunks = [];
        let length = 0;
        if (reader) {
          while (true) {
            const part = await reader.read();
            if (part.done) break;
            length += part.value.length;
            if (length > 8192) { await reader.cancel(); throw new ApiError(413, "Request too large."); }
            chunks.push(part.value);
          }
        }
        const bytes = new Uint8Array(length);
        let position = 0;
        for (const chunk of chunks) { bytes.set(chunk, position); position += chunk.length; }
        const text = new TextDecoder().decode(bytes);
        let input;
        try { input = JSON.parse(text); } catch { throw new ApiError(400, "Invalid JSON."); }
        const camera = await authenticate(req, input.camera_id, "upload");
        const sequence = input.first_sequence, start = Date.parse(input.capture_start), now = Date.now();
        if (!/^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i.test(input.session_id || "") ||
            !Number.isSafeInteger(sequence) || sequence < 0 || sequence > 1e12 || !Number.isFinite(start))
          throw new ApiError(400, "Invalid session, sequence or capture time.");
        if (start < now - RETENTION * 1000) throw new ApiError(410, "Video has expired.");
        if (start > now + 5000) throw new ApiError(400, "Camera clock is in the future.");
        if (sequence === 0) {
          if (camera.active_session && camera.active_session !== input.session_id &&
              Date.parse(camera.active_capture_start) > start + 20)
            throw new ApiError(409, "An older session cannot replace a newer capture session.");
          await remote(`/rest/v1/breathing_video_devices?camera_id=eq.${encodeURIComponent(input.camera_id)}`,
            { method: "PATCH", body: JSON.stringify({ active_session: input.session_id,
              active_capture_start: new Date(start).toISOString() }) });
        } else if (camera.active_session !== input.session_id) {
          throw new ApiError(409, "This capture session has been replaced. Restart the uploader.");
        }
        const segments = Array.from({ length: COUNT }, (_, i) => ({
          camera_id: input.camera_id, session_id: input.session_id, sequence: sequence + i,
          object_path: `${input.camera_id}/${input.session_id}/${String(sequence+i).padStart(12,"0")}.ts`,
          capture_start: new Date(start + i * 2000).toISOString(),
          capture_end: new Date(start + (i+1) * 2000).toISOString(),
          expires_at: new Date(start + i * 2000 + RETENTION * 1000).toISOString(), fps: FPS, frame_count: 20,
        }));
        await remote("/rest/v1/breathing_video_segments?on_conflict=camera_id,session_id,sequence", {
          method: "POST", headers: { Prefer: "resolution=ignore-duplicates" }, body: JSON.stringify(segments),
        });
        const stored = await rows("breathing_video_segments", { camera_id: `eq.${input.camera_id}`,
          session_id: `eq.${input.session_id}`, sequence: `gte.${sequence}`, order: "sequence.asc", limit: String(COUNT) });
        if (stored.length !== COUNT || stored.some((row,i) => Number(row.sequence) !== sequence+i ||
            Date.parse(row.capture_start) !== start+i*2000)) throw new ApiError(409, "Reservation conflicts with existing timestamps.");
        const ready = await rows("breathing_video_ready", { camera_id: `eq.${input.camera_id}`,
          session_id: `eq.${input.session_id}`, sequence: `gte.${sequence}`, select: "sequence", limit: "1000" });
        const uploaded = new Set(ready.map((row) => Number(row.sequence)));
        // Mint in small batches; video bytes go directly from Pi to Storage.
        const signed = [];
        for (let offset = 0; offset < stored.length; offset += 5) {
          signed.push(...await Promise.all(stored.slice(offset,offset+5).map(async (row) => ({
            sequence: Number(row.sequence), capture_start: row.capture_start,
            ...(uploaded.has(Number(row.sequence)) ? { uploaded: true } : { upload_url: await signedUpload(row.object_path) }),
          }))));
        }
        return json({ fps: FPS, segment_seconds: SEGMENT, segments: signed });
      }
      if (action === "latest" && req.method === "GET") {
        const cameraId = url.searchParams.get("camera_id");
        const camera = await authenticate(req, cameraId, "read");
        if (!camera.active_session) throw new ApiError(409, "No capture session is available.");
        const segments = (await rows("breathing_video_ready", { camera_id: `eq.${cameraId}`,
          session_id: `eq.${camera.active_session}`, order: "capture_end.desc", limit: String(COUNT) })).reverse();
        validateWindow(segments);
        const files = await Promise.all(segments.map(async (row) => ({ sequence: Number(row.sequence),
          capture_start: row.capture_start, capture_end: row.capture_end, etag: row.etag,
          download_url: await signedDownload(row.object_path) })));
        return json({ camera_id: cameraId, session_id: camera.active_session, fps: FPS,
          frame_count: 300, duration_seconds: 30, segments: files });
      }
      throw new ApiError(404, "Unknown operation.");
    } catch (error) {
      const status = error instanceof ApiError ? error.status : 500;
      if (status >= 500) console.error("Video operation failed", { status, upstream_status: error.upstreamStatus });
      return json({ error: status === 500 ? "Video service failed." : error.message }, status);
    }
  };
}
if (typeof Deno !== "undefined") Deno.serve(createHandler((name) => Deno.env.get(name)));
