-- 신규 결과 테이블. 대상 Supabase 프로젝트의 SQL Editor에서 1회 실행합니다.
-- 같은 이름의 테이블이 있으면 중단합니다. 기존 테이블을 수정/삭제하지 않습니다.
begin;
create table public.babycam_analysis_results (
  batch_id text primary key,
  stream_id text not null,
  start_seq bigint not null check (start_seq >= 0),
  end_seq bigint not null check (end_seq = start_seq + 14),
  segments jsonb not null check (jsonb_array_length(segments) = 15),
  model_signature text not null,
  status text not null check (status in ('anomaly_candidate', 'below_threshold', 'unscored')),
  is_anomaly boolean,
  anomaly_score double precision,
  threshold double precision,
  pred_rr_bpm double precision,
  wave_mse double precision,
  bpm_mse double precision,
  waveform jsonb,
  reason text,
  source_duration_sec double precision,
  duration_sec double precision,
  continuity jsonb,
  processing_sec double precision not null check (processing_sec >= 0),
  created_at timestamptz not null default now(),
  constraint result_state_consistency check ((
    (status = 'unscored' and is_anomaly is null and anomaly_score is null
      and pred_rr_bpm is null and wave_mse is null and bpm_mse is null and waveform is null)
    or
    (status in ('anomaly_candidate', 'below_threshold')
      and is_anomaly is not null and anomaly_score is not null and threshold is not null
      and anomaly_score >= 0 and anomaly_score < 'Infinity'::double precision
      and threshold >= 0 and threshold < 'Infinity'::double precision
      and pred_rr_bpm is not null and pred_rr_bpm > 0 and pred_rr_bpm < 'Infinity'::double precision
      and wave_mse is not null and wave_mse >= 0 and wave_mse < 'Infinity'::double precision
      and bpm_mse is not null and bpm_mse >= 0 and bpm_mse < 'Infinity'::double precision
      and waveform is not null and jsonb_array_length(waveform->'x_10hz') = 300
      and duration_sec is not null and duration_sec between 29.99 and 30.01
      and is_anomaly = (anomaly_score > threshold)
      and is_anomaly = (status = 'anomaly_candidate'))
  ) is true)
);
create index babycam_results_stream_seq on public.babycam_analysis_results (stream_id, end_seq desc);
alter table public.babycam_analysis_results enable row level security;
revoke all on public.babycam_analysis_results from public, anon, authenticated;
grant select, insert on public.babycam_analysis_results to service_role;
comment on table public.babycam_analysis_results is
  'AIR-400 검토용 분석 결과. 신뢰된 Python 서버만 접근. 임상적 정상/무호흡 확정 판정 아님.';
notify pgrst, 'reload schema';
commit;
