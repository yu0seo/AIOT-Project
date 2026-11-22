-- Reconfigure this project's existing retention jobs; do not expose the Vault secret.
-- Replace the public API key below before running in the Supabase SQL editor.
do $$
declare
  publishable_key text := 'REPLACE_WITH_PUBLISHABLE_KEY';
begin
  if publishable_key = 'REPLACE_WITH_PUBLISHABLE_KEY' then
    raise exception 'Set the project publishable API key first';
  end if;
  perform cron.schedule('breathing-video-retention', '10 seconds', format($worker$
    select net.http_post(
      url := 'https://wwkphksqyjqsjouoamly.supabase.co/functions/v1/breathing-video/cleanup',
      headers := jsonb_build_object('Content-Type','application/json','apikey',%L,
        'x-cleanup-key',(select decrypted_secret from vault.decrypted_secrets
          where name='breathing_video_cleanup_key')),
      body := '{}'::jsonb, timeout_milliseconds := 8000
    );
  $worker$, publishable_key));
  perform cron.schedule('breathing-video-cron-log-prune','23 * * * *',$job$
    delete from cron.job_run_details
    where jobid in (select jobid from cron.job where jobname in
      ('breathing-video-retention','breathing-video-cron-log-prune'))
      and end_time < now() - interval '1 day';
  $job$);
end $$;
