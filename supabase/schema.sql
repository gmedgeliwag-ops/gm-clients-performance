-- Run this once in Supabase: Dashboard -> SQL Editor -> New Query -> paste -> Run

create table if not exists public.orders (
  company text not null,
  row_key text not null,
  order_id text,
  tracking_number text,
  fee_paid_to_delivery numeric,
  status text,
  assigning_seller text,
  customer_care_staff text,
  customer_name text,
  phone_number text,
  commune_village text,
  district text,
  province_city text,
  day_created date,
  product_name text,
  unit_price numeric,
  total_price numeric,
  ad_id text,
  date_sent_to_partner text,
  marketer text,
  return_reason text,
  region_raw text,
  region_norm text,
  first_delivery text,
  order_delivered_date text,
  order_returned_date text,
  customer_type text,
  shipping_info text,
  item_handler text,
  orders_source text,
  expected_delivery_date text,
  detail_address text,
  warehouse text,
  variation_id text,
  promotion_id text,
  is_upsell boolean not null default false,
  is_shipment boolean not null default false,
  is_delivered boolean not null default false,
  is_rts boolean not null default false,
  rts_reason_norm text,
  synced_at timestamptz not null default now(),
  primary key (company, row_key)
);

create index if not exists idx_orders_company_date on public.orders (company, day_created);
create index if not exists idx_orders_company_status on public.orders (company, status);
create index if not exists idx_orders_company_product on public.orders (company, product_name);
create index if not exists idx_orders_synced_at on public.orders (synced_at);
create index if not exists idx_orders_agg_cover on public.orders (company, day_created)
  include (region_norm, product_name, is_shipment, is_delivered, is_rts, is_upsell, item_handler, rts_reason_norm, unit_price);
create index if not exists idx_orders_search on public.orders using gin (
  to_tsvector('simple',
    coalesce(customer_name,'') || ' ' || coalesce(tracking_number,'') || ' ' || coalesce(phone_number,'')
  )
);

alter table public.orders enable row level security;

drop policy if exists "Public read access" on public.orders;
create policy "Public read access" on public.orders
  for select
  using (true);

-- Aggregates are materialized (pre-computed) so the dashboard reads are instant
-- instead of re-scanning the whole orders table on every request. They are
-- refreshed by calling public.refresh_dashboard_views() after each sync.

drop view if exists public.v_daily_stats cascade;
drop view if exists public.v_region_product_daily cascade;
drop view if exists public.v_rts_reasons_daily cascade;
drop view if exists public.v_telesales_daily cascade;
drop view if exists public.v_status_daily cascade;
drop view if exists public.v_meta cascade;
drop materialized view if exists public.v_daily_stats cascade;
drop materialized view if exists public.v_region_product_daily cascade;
drop materialized view if exists public.v_rts_reasons_daily cascade;
drop materialized view if exists public.v_telesales_daily cascade;
drop materialized view if exists public.v_status_daily cascade;

create materialized view public.v_daily_stats as
select company, day_created as date,
  count(*) filter (where is_shipment) as orders,
  count(*) filter (where is_delivered) as delivered,
  count(*) filter (where is_rts) as rts,
  coalesce(sum(unit_price) filter (where is_delivered), 0) as sales,
  count(*) filter (where not is_upsell) as all_orders
from public.orders
where not is_upsell and day_created is not null
group by company, day_created;
create unique index v_daily_stats_uidx on public.v_daily_stats (company, date);

create materialized view public.v_region_product_daily as
select company, day_created as date, region_norm as region, product_name as product,
  count(*) filter (where is_shipment) as orders,
  count(*) filter (where is_delivered) as delivered,
  count(*) filter (where is_rts) as rts,
  coalesce(sum(unit_price) filter (where is_delivered), 0) as sales
from public.orders
where is_shipment and region_norm is not null and day_created is not null
group by company, day_created, region_norm, product_name;
create unique index v_region_product_daily_uidx on public.v_region_product_daily (company, date, region, product);

create materialized view public.v_rts_reasons_daily as
select company, day_created as date, rts_reason_norm as reason, count(*) as count
from public.orders
where is_rts and day_created is not null
group by company, day_created, rts_reason_norm;
create unique index v_rts_reasons_daily_uidx on public.v_rts_reasons_daily (company, date, reason);

create materialized view public.v_telesales_daily as
select company, day_created as date, item_handler as handler,
  count(*) as count,
  coalesce(sum(unit_price), 0) as sales
from public.orders
where is_upsell and day_created is not null
group by company, day_created, item_handler;
create unique index v_telesales_daily_uidx on public.v_telesales_daily (company, date, handler);

-- Order status breakdown (Unfulfilled vs Fulfilled Sales columns on the Overview).
-- Grouped by raw status so the dashboard can bucket/relabel client-side without
-- another migration if the status list changes.
create materialized view public.v_status_daily as
select company, day_created as date, status,
  count(*) as count,
  coalesce(sum(unit_price), 0) as value
from public.orders
where not is_upsell and day_created is not null and status is not null
group by company, day_created, status;
create unique index v_status_daily_uidx on public.v_status_daily (company, date, status);

create or replace view public.v_meta as
select max(synced_at) as last_synced_at from public.orders;

grant select on public.v_daily_stats to anon, authenticated;
grant select on public.v_region_product_daily to anon, authenticated;
grant select on public.v_rts_reasons_daily to anon, authenticated;
grant select on public.v_telesales_daily to anon, authenticated;
grant select on public.v_status_daily to anon, authenticated;
grant select on public.v_meta to anon, authenticated;

create or replace function public.refresh_dashboard_views()
returns void
language plpgsql
security definer
set search_path = public
as $$
begin
  refresh materialized view concurrently public.v_daily_stats;
  refresh materialized view concurrently public.v_region_product_daily;
  refresh materialized view concurrently public.v_rts_reasons_daily;
  refresh materialized view concurrently public.v_telesales_daily;
  refresh materialized view concurrently public.v_status_daily;
end;
$$;

revoke all on function public.refresh_dashboard_views() from public;
grant execute on function public.refresh_dashboard_views() to service_role;
