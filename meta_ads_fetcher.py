"""
Meta Ads Fetcher
================
Fetches campaigns, ad sets, ads, and insights from the Meta (Facebook)
Marketing API using your own Meta App Access Token.

Requirements:
    pip install requests

Usage:
    python meta_ads_fetcher.py \
        --token YOUR_ACCESS_TOKEN \
        --account act_XXXXXXXXXX \
        --since 2024-01-01 \
        --until 2024-12-31 \
        --output output.json
"""

import argparse
import json
import time
import sys
import requests

API_VERSION = "v21.0"
BASE_URL = f"https://graph.facebook.com/{API_VERSION}"

# ---------------------------------------------------------------------------
# Fields to fetch per object level
# ---------------------------------------------------------------------------

CAMPAIGN_FIELDS = ",".join([
    "id", "name", "status", "objective", "buying_type",
    "daily_budget", "lifetime_budget", "budget_remaining",
    "start_time", "stop_time", "created_time", "updated_time",
    "bid_strategy", "special_ad_categories", "effective_status",
    "spend_cap",
])

ADSET_FIELDS = ",".join([
    "id", "name", "status", "campaign_id",
    "daily_budget", "lifetime_budget", "budget_remaining",
    "bid_amount", "bid_strategy", "billing_event",
    "optimization_goal", "targeting",
    "start_time", "end_time", "created_time", "updated_time",
    "effective_status", "destination_type",
    "instagram_actor_id", "promoted_object",
    "rf_prediction_id",
])

AD_FIELDS = ",".join([
    "id", "name", "status", "adset_id", "campaign_id",
    "creative", "tracking_specs",
    "conversion_specs", "bid_amount",
    "created_time", "updated_time", "effective_status",
    "ad_review_feedback",
])

INSIGHT_FIELDS = ",".join([
    "account_id", "account_name",
    "campaign_id", "campaign_name",
    "adset_id", "adset_name",
    "ad_id", "ad_name",
    "date_start", "date_stop",
    "impressions", "reach", "frequency",
    "clicks", "unique_clicks",
    "spend", "cpc", "cpm", "ctr", "cpp",
    "actions", "action_values",
    "conversions", "conversion_values",
    "cost_per_action_type",
    "cost_per_unique_click",
    "outbound_clicks", "outbound_clicks_ctr",
    "video_play_actions", "video_thruplay_watched_actions",
    "video_p25_watched_actions", "video_p50_watched_actions",
    "video_p75_watched_actions", "video_p100_watched_actions",
    "website_purchase_roas",
    "objective", "optimization_goal",
    "buying_type",
])

INSIGHT_BREAKDOWNS = ""          # set e.g. "age,gender" to add breakdowns


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def paginate(url: str, params: dict) -> list:
    """Walk through all pages of a Graph API edge and return merged results."""
    results = []
    while url:
        resp = requests.get(url, params=params, timeout=30)
        resp.raise_for_status()
        data = resp.json()

        if "error" in data:
            raise RuntimeError(f"API error: {data['error']}")

        results.extend(data.get("data", []))
        paging = data.get("paging", {})
        url = paging.get("next")   # None when last page
        params = {}                 # next URL already contains params
    return results


def poll_async_job(job_id: str, token: str) -> list:
    """Poll an async insights job until complete, then return all rows."""
    url = f"{BASE_URL}/{job_id}"
    params = {"access_token": token}

    for attempt in range(120):          # up to ~10 minutes
        resp = requests.get(url, params=params, timeout=30)
        resp.raise_for_status()
        job = resp.json()

        async_status = job.get("async_status", "")
        pct = job.get("async_percent_completion", 0)
        print(f"  Insights job {job_id}: {async_status} ({pct}%)", flush=True)

        if async_status in ("Job Completed",):
            result_url = f"{BASE_URL}/{job_id}/insights"
            return paginate(result_url, {"access_token": token})

        if async_status in ("Job Failed", "Job Skipped"):
            raise RuntimeError(f"Async insights job failed: {job}")

        time.sleep(5)

    raise TimeoutError("Async insights job timed out after 10 minutes.")


def fetch_insights(account_id: str, token: str, since: str, until: str, level: str = "ad") -> list:
    """Kick off an async insights report and return results."""
    url = f"{BASE_URL}/{account_id}/insights"
    payload = {
        "access_token": token,
        "fields": INSIGHT_FIELDS,
        "level": level,
        "time_range": json.dumps({"since": since, "until": until}),
        "time_increment": 1,           # daily breakdown
        "limit": 500,
    }
    if INSIGHT_BREAKDOWNS:
        payload["breakdowns"] = INSIGHT_BREAKDOWNS

    resp = requests.post(url, data=payload, timeout=30)
    resp.raise_for_status()
    result = resp.json()

    if "error" in result:
        raise RuntimeError(f"API error starting insights job: {result['error']}")

    # Synchronous response (small accounts)
    if "data" in result:
        rows = result["data"]
        next_url = result.get("paging", {}).get("next")
        while next_url:
            r = requests.get(next_url, timeout=30)
            r.raise_for_status()
            page = r.json()
            rows.extend(page.get("data", []))
            next_url = page.get("paging", {}).get("next")
        return rows

    # Async job
    job_id = result.get("report_run_id")
    if job_id:
        return poll_async_job(job_id, token)

    raise RuntimeError(f"Unexpected insights response: {result}")


# ---------------------------------------------------------------------------
# Main fetch logic
# ---------------------------------------------------------------------------

def fetch_all(account_id: str, token: str, since: str, until: str) -> dict:
    common = {"access_token": token, "limit": 200}

    print("Fetching campaigns...")
    campaigns = paginate(
        f"{BASE_URL}/{account_id}/campaigns",
        {**common, "fields": CAMPAIGN_FIELDS},
    )
    print(f"  {len(campaigns)} campaigns found.")

    print("Fetching ad sets...")
    adsets = paginate(
        f"{BASE_URL}/{account_id}/adsets",
        {**common, "fields": ADSET_FIELDS},
    )
    print(f"  {len(adsets)} ad sets found.")

    print("Fetching ads...")
    ads = paginate(
        f"{BASE_URL}/{account_id}/ads",
        {**common, "fields": AD_FIELDS},
    )
    print(f"  {len(ads)} ads found.")

    print("Fetching insights (ad level, daily)...")
    insights = fetch_insights(account_id, token, since, until, level="ad")
    print(f"  {len(insights)} insight rows fetched.")

    return {
        "account_id": account_id,
        "date_range": {"since": since, "until": until},
        "campaigns": campaigns,
        "adsets": adsets,
        "ads": ads,
        "insights": insights,
    }


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(description="Fetch Meta Ads data to JSON.")
    parser.add_argument("--token",   required=True, help="Meta App Access Token")
    parser.add_argument("--account", required=True, help="Ad Account ID, e.g. act_123456789")
    parser.add_argument("--since",   required=True, help="Start date YYYY-MM-DD")
    parser.add_argument("--until",   required=True, help="End date YYYY-MM-DD")
    parser.add_argument("--output",  default="meta_ads_output.json", help="Output JSON file path")
    args = parser.parse_args()

    account_id = args.account if args.account.startswith("act_") else f"act_{args.account}"

    try:
        data = fetch_all(account_id, args.token, args.since, args.until)
    except requests.HTTPError as e:
        print(f"HTTP error: {e}\nResponse: {e.response.text}", file=sys.stderr)
        sys.exit(1)
    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)

    with open(args.output, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, default=str)

    print(f"\nData saved to {args.output}")


if __name__ == "__main__":
    main()
