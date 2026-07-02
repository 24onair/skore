"use strict";

const map = new maplibregl.Map({
  container: "map",
  style: {
    version: 8,
    sources: {
      osm: {
        type: "raster",
        tiles: ["https://tile.openstreetmap.org/{z}/{x}/{y}.png"],
        tileSize: 256,
        attribution: "© OpenStreetMap contributors",
      },
    },
    layers: [{ id: "osm", type: "raster", source: "osm" }],
  },
  center: [8.1, 46.2],
  zoom: 8,
});

// --- helpers ----------------------------------------------------------------
// Display offset (seconds) applied to absolute clock times; 0 = UTC.
let TZ_OFFSET = 0;

function secToClock(s, offset = TZ_OFFSET) {
  // Absolute time-of-day, shifted into local time for display.
  if (s == null) return "—";
  return fmt(s + offset);
}

function secToHMS(s) {
  // A duration (no timezone shift).
  if (s == null) return "—";
  return fmt(s);
}

function fmt(s) {
  s = ((s % 86400) + 86400) % 86400;
  const h = Math.floor(s / 3600);
  const m = Math.floor((s % 3600) / 60);
  const sec = s % 60;
  return `${String(h).padStart(2, "0")}:${String(m).padStart(2, "0")}:${String(sec).padStart(2, "0")}`;
}

function circlePolygon(lat, lon, radiusM, steps = 72) {
  const ring = [];
  const mPerLat = 110540;
  const mPerLon = 111320 * Math.cos((lat * Math.PI) / 180);
  for (let i = 0; i <= steps; i++) {
    const a = (i / steps) * 2 * Math.PI;
    ring.push([lon + (radiusM * Math.cos(a)) / mPerLon, lat + (radiusM * Math.sin(a)) / mPerLat]);
  }
  return ring;
}

function cylinderColor(kind) {
  if (kind === "sss") return "#34d399";
  if (kind === "ess") return "#fbbf24";
  if (kind === "goal") return "#f87171";
  if (kind === "takeoff") return "#8b97a7";
  return "#38bdf8";
}

function setSourceData(id, data, addLayer) {
  const src = map.getSource(id);
  if (src) {
    src.setData(data);
  } else {
    map.addSource(id, { type: "geojson", data });
    addLayer();
  }
}

// --- rendering --------------------------------------------------------------
function render(payload) {
  const { track, task, analysis, meta } = payload;
  TZ_OFFSET = (meta && meta.utc_offset) || 0;

  // Cylinders
  const cyl = {
    type: "FeatureCollection",
    features: task.turnpoints.map((t) => ({
      type: "Feature",
      properties: { kind: t.kind, color: cylinderColor(t.kind) },
      geometry: { type: "Polygon", coordinates: [circlePolygon(t.lat, t.lon, Math.max(t.radius, 30))] },
    })),
  };
  setSourceData("cyl", cyl, () => {
    map.addLayer({ id: "cyl-fill", type: "fill", source: "cyl",
      paint: { "fill-color": ["get", "color"], "fill-opacity": 0.18 } });
    map.addLayer({ id: "cyl-line", type: "line", source: "cyl",
      paint: { "line-color": ["get", "color"], "line-width": 2.8, "line-opacity": 0.95 } });
  });

  // Track
  const trackLine = {
    type: "Feature",
    geometry: { type: "LineString", coordinates: track.points.map(([la, lo]) => [lo, la]) },
  };
  setSourceData("track", trackLine, () => {
    map.addLayer({ id: "track", type: "line", source: "track",
      layout: { "line-join": "round", "line-cap": "round" },
      paint: { "line-color": "#38bdf8", "line-width": 2.2 } });
  });

  // Optimized route
  const routeLine = {
    type: "Feature",
    geometry: { type: "LineString", coordinates: analysis.route.points.map(([la, lo]) => [lo, la]) },
  };
  setSourceData("route", routeLine, () => {
    map.addLayer({ id: "route", type: "line", source: "route",
      paint: { "line-color": "#fb923c", "line-width": 2, "line-dasharray": [2, 1.5] } });
  });

  // Turnpoint markers
  const marks = {
    type: "FeatureCollection",
    features: task.turnpoints.map((t) => ({
      type: "Feature",
      properties: { label: t.name || t.kind },
      geometry: { type: "Point", coordinates: [t.lon, t.lat] },
    })),
  };
  setSourceData("marks", marks, () => {
    map.addLayer({ id: "marks", type: "circle", source: "marks",
      paint: { "circle-radius": 3, "circle-color": "#e6edf3" } });
    map.addLayer({ id: "marks-label", type: "symbol", source: "marks",
      layout: { "text-field": ["get", "label"], "text-size": 11, "text-offset": [0, 1.1], "text-anchor": "top" },
      paint: { "text-color": "#e6edf3", "text-halo-color": "#0f1419", "text-halo-width": 1.2 } });
  });

  // Fit bounds to the track
  const b = new maplibregl.LngLatBounds();
  track.points.forEach(([la, lo]) => b.extend([lo, la]));
  task.turnpoints.forEach((t) => b.extend([t.lon, t.lat]));
  if (!b.isEmpty()) map.fitBounds(b, { padding: 60, duration: 600 });

  renderPanel(track, analysis, meta);
}

function renderPanel(track, a, meta) {
  document.getElementById("results").hidden = false;

  const verdict = document.getElementById("verdict");
  if (!a.started) {
    verdict.className = "nostart";
    verdict.textContent = "⛔ 유효한 출발 없음 (SSS 미통과)";
  } else if (a.in_goal) {
    verdict.className = "goal";
    verdict.textContent = "🏁 골 도착!";
  } else if (a.reached_ess) {
    verdict.className = "ess";
    verdict.textContent = "🟡 ESS 통과 (골 미도착)";
  } else {
    verdict.className = "landed";
    verdict.textContent = "🪂 코스 중 착륙";
  }

  const tz = (meta && meta.tz_label) || "UTC";
  const rows = [
    ["선수", track.pilot || "—"],
    ["글라이더", track.glider || "—"],
    ["비행거리", `${a.distance_km} km`],
    ["과제거리", `${a.task_distance_km} km`],
    ["출발 시각", secToClock(a.start_time)],
    ["ESS 시각", secToClock(a.ess_time)],
    ["골 시각", secToClock(a.goal_time)],
    ["구간시간(SS)", a.ss_elapsed != null ? secToHMS(a.ss_elapsed) : "—"],
    ["평균속도", a.speed_kmh != null ? `${a.speed_kmh} km/h` : "—"],
    ["시간대", tz],
  ];
  document.getElementById("metrics").innerHTML = rows
    .map(([k, v]) => `<dt>${k}</dt><dd>${v}</dd>`)
    .join("");

  document.getElementById("tags").innerHTML = a.tags.length
    ? a.tags.map((t) => `<li><span class="k">${t.kind}</span> <span>${t.name}</span> <span>${secToClock(t.time)}</span></li>`).join("")
    : `<li class="muted">기록 없음</li>`;
}

// --- form -------------------------------------------------------------------
document.getElementById("form").addEventListener("submit", async (e) => {
  e.preventDefault();
  const igc = document.getElementById("igc").files[0];
  const task = document.getElementById("task").files[0];
  const status = document.getElementById("status");
  const btn = document.getElementById("go");
  if (!igc || !task) return;

  btn.disabled = true;
  status.className = "muted";
  status.textContent = "분석 중…";

  const fd = new FormData();
  fd.append("igc", igc);
  fd.append("task", task);

  try {
    const res = await fetch("/api/analyze", { method: "POST", body: fd });
    if (!res.ok) {
      const err = await res.json().catch(() => ({ detail: res.statusText }));
      throw new Error(err.detail || "분석 실패");
    }
    const payload = await res.json();
    status.textContent = `${payload.track.fix_count.toLocaleString()}개 fix 분석 완료`;
    render(payload);
  } catch (err) {
    status.className = "err";
    status.textContent = "오류: " + err.message;
  } finally {
    btn.disabled = false;
  }
});
