"use strict";
const el = id => document.getElementById(id);
const labels = {anomaly_candidate:"이상 후보",below_threshold:"임계값 이하",unscored:"분석 불가"};
const kind = s => s === "anomaly_candidate" ? "alert" : s === "unscored" ? "unknown" : "";
const number = (x, digits=1) => typeof x === "number" && Number.isFinite(x) ? x.toFixed(digits) : "—";
const date = x => x && !Number.isNaN(Date.parse(x)) ? new Date(x).toLocaleString("ko-KR") : "—";
let lastVersion = "";

function renderRows(rows) {
  el("history").replaceChildren();
  el("empty").hidden = rows.length > 0;
  for (const row of rows) {
    const tr = document.createElement("tr");
    const values = [date(row.created_at), `${row.start_seq}–${row.end_seq}`, labels[row.status] || "분석 불가", number(row.pred_rr_bpm), number(row.anomaly_score,3)];
    values.forEach((value,index) => {
      const td = document.createElement("td"); td.textContent = value;
      if (index === 2) td.className = "badge " + kind(row.status);
      tr.append(td);
    });
    el("history").append(tr);
  }
  const row = rows[0];
  if (!row) {
    el("status").textContent = "대기 중"; el("status").className = "";
    el("timestamp").textContent = "—"; el("bpm").textContent = "—"; el("score").textContent = "—";
    el("reason").textContent = ""; el("wave").setAttribute("points", "");
    el("plot").setAttribute("aria-label", "분석 가능한 호흡 파형 없음");
    el("plot-caption").textContent = "분석 가능한 파형이 도착하면 표시됩니다.";
    return;
  }
  el("status").textContent = labels[row.status] || "분석 불가";
  el("status").className = kind(row.status);
  el("timestamp").textContent = date(row.created_at);
  el("bpm").textContent = number(row.pred_rr_bpm);
  el("score").textContent = row.status === "unscored" ? "—" : `${number(row.anomaly_score,3)} / ${number(row.threshold,3)}`;
  el("reason").textContent = row.status === "unscored" ? row.reason || "분석할 수 없는 구간입니다." : "";
  const wave = row.waveform?.x_10hz;
  const valid = row.status !== "unscored" && Array.isArray(wave) && wave.length === 300 && wave.every(Number.isFinite);
  if (valid) {
    const lo = Math.min(...wave), hi = Math.max(...wave), span = Math.max(hi-lo, 0.001);
    el("wave").setAttribute("points",wave.map((y,i) => `${i/299*900},${220-(y-lo)/span*200}`).join(" "));
    el("plot").setAttribute("aria-label",`최근 30초 호흡 파형. ${labels[row.status]}, 추정 호흡수 ${number(row.pred_rr_bpm)}회/분`);
  } else {
    el("wave").setAttribute("points", "");
    el("plot").setAttribute("aria-label", "분석 가능한 호흡 파형 없음");
  }
  el("plot-caption").textContent = valid ? "30초 호흡 파형 · 상대 크기" : "분석 가능한 파형이 없습니다.";
}

async function refresh() {
  try {
    const response = await fetch("/api/results", {cache:"no-store", signal:AbortSignal.timeout(5000)});
    if (!response.ok) throw new Error("connection");
    const data = await response.json();
    el("connection").textContent = data.mode === "preview" ? "미연결 미리보기" : data.error ? "결과 조회 연결 오류" : data.last_success_at ? "연결됨 · 자동 갱신 중" : "Supabase 연결 중…";
    const version = JSON.stringify(data.results);
    if (version !== lastVersion) { renderRows(data.results); lastVersion = version; }
    const notice = el("notice");
    notice.classList.toggle("error",Boolean(data.error));
    notice.textContent = data.error ? `${data.error} 마지막 성공: ${date(data.last_success_at)}`
      : data.mode === "preview" ? "화면 미리보기입니다. .env 설정 후 서버를 다시 실행하면 실제 결과를 읽습니다."
      : !data.results.length ? "첫 30초 분석 결과를 기다리고 있습니다."
      : `마지막 DB 확인: ${date(data.last_success_at)} · 분석 구간의 실제 촬영시각 연속성은 별도 확인이 필요합니다.`;
  } catch {
    el("connection").textContent = "결과 서버 연결 끊김";
    el("notice").classList.add("error");
    el("notice").textContent = "결과 서버에 연결할 수 없습니다. 마지막으로 받은 결과를 표시하며 다시 연결하고 있습니다.";
  } finally { setTimeout(refresh,1000); }
}
refresh();
