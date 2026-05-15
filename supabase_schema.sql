-- vicidial-insights cache schema
-- Run via Supabase SQL editor or `supabase db push`.
--
-- Purpose: cache derived data so the dashboard never queries Vicidial directly.
-- Refreshed by the nightly cron job in the Railway service.

create table if not exists lead_score_snapshots (
    id              bigserial primary key,
    snapshot_at     timestamptz not null default now(),
    lead_id         bigint not null,
    score           numeric(5,1) not null,
    recommendation  text not null,
    reasons         jsonb not null default '[]'::jsonb,
    state           text,
    campaign_id     text,
    called_count    int,
    last_dispo      text,
    last_call_at    timestamptz
);

create index if not exists lead_score_snapshots_snapshot_idx on lead_score_snapshots (snapshot_at desc);
create index if not exists lead_score_snapshots_lead_idx on lead_score_snapshots (lead_id, snapshot_at desc);
create index if not exists lead_score_snapshots_score_idx on lead_score_snapshots (snapshot_at desc, score desc);

create table if not exists agent_stats_snapshots (
    id              bigserial primary key,
    snapshot_at     timestamptz not null default now(),
    period_days     int not null,
    "user"          text not null,
    full_name       text,
    calls_handled   int not null,
    sales           int not null,
    close_rate      numeric(5,4) not null,
    talk_seconds    bigint not null,
    avg_talk_sec    numeric(7,1) not null
);

create index if not exists agent_stats_snapshot_idx on agent_stats_snapshots (snapshot_at desc);

create table if not exists weekly_summaries (
    id              bigserial primary key,
    generated_at    timestamptz not null default now(),
    lang            text not null check (lang in ('es', 'en')),
    summary_text    text not null,
    top_leads_count int not null,
    model           text not null default 'claude-haiku-4-5-20251001',
    input_tokens    int,
    output_tokens   int
);

create index if not exists weekly_summaries_generated_idx on weekly_summaries (generated_at desc);

create table if not exists disposition_snapshots (
    id              bigserial primary key,
    snapshot_at     timestamptz not null default now(),
    period_days     int not null,
    dispo           text not null,
    count           int not null
);

create index if not exists disposition_snapshot_idx on disposition_snapshots (snapshot_at desc);
