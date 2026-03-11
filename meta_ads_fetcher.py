"""
Meta Ad Library Fetcher — Competitor Analysis
==============================================
Fetches competitor ads from Meta's public Ad Library API.
No special permissions needed beyond a standard Meta user access token.

Official docs: https://www.facebook.com/ads/library/api/

Requirements:
    pip install requests

Usage examples:

  # Search by competitor keyword
  python meta_ads_fetcher.py \\
      --token YOUR_ACCESS_TOKEN \\
      --search "Nike shoes" \\
      --countries US \\
      --output nike_ads.json

  # Search by specific competitor Page IDs (up to 10)
  python meta_ads_fetcher.py \\
      --token YOUR_ACCESS_TOKEN \\
      --page-ids 123456789 987654321 \\
      --countries US GB \\
      --status ALL \\
      --output competitor_pages.json

  # Filter to only video ads on Instagram
  python meta_ads_fetcher.py \\
      --token YOUR_ACCESS_TOKEN \\
      --search "protein powder" \\
      --countries US \\
      --media-type VIDEO \\
      --platforms INSTAGRAM \\
      --output protein_video_ads.json
"""

import argparse
import json
import sys
import time
import requests

API_VERSION = "v21.0"
AD_LIBRARY_URL = f"https://graph.facebook.com/{API_VERSION}/ads_archive"

# All fields the Ad Library API can return
# Basic fields (available for all ad types)
BASIC_FIELDS = [
    "id",                          # Ad Library ID
    "ad_creative_bodies",          # List of ad copy text bodies
    "ad_creative_link_captions",   # Link captions in the ad
    "ad_creative_link_descriptions",
    "ad_creative_link_titles",
    "ad_delivery_start_time",      # When the ad started running
    "ad_delivery_stop_time",       # When the ad stopped (null if still active)
    "ad_snapshot_url",             # URL to archived ad preview
    "currency",
    "page_id",
    "page_name",
    "publisher_platforms",         # FACEBOOK, INSTAGRAM, etc.
    "languages",
    "bylines",
    "estimated_audience_size",
]

# Extended fields available for political/issue ads and all ads in EU/UK
EXTENDED_FIELDS = [
    "spend",                       # Estimated spend range {"lower_bound", "upper_bound"}
    "impressions",                 # Estimated impressions range
    "demographic_distribution",    # Age/gender breakdown
    "delivery_by_region",          # Geographic reach breakdown
    "target_ages",
    "target_gender",
    "target_locations",
    "funding_entity",              # Who paid for the ad
]


def paginate(params: dict, max_results: int = 0) -> list:
    """Walk all pages of the Ad Library API and return merged results."""
    results = []
    url = AD_LIBRARY_URL

    while url:
        resp = requests.get(url, params=params, timeout=30)
        resp.raise_for_status()
        data = resp.json()

        if "error" in data:
            error = data["error"]
            raise RuntimeError(
                f"API error {error.get('code')}: {error.get('message')}\n"
                f"Type: {error.get('type')}\n"
                f"Tip: {error.get('error_user_msg', '')}"
            )

        results.extend(data.get("data", []))
        print(f"  Fetched {len(results)} ads so far...", end="\r", flush=True)

        if max_results and len(results) >= max_results:
            results = results[:max_results]
            break

        paging = data.get("paging", {})
        next_url = paging.get("next")
        if not next_url:
            break

        # next URL already contains all params — clear params dict
        url = next_url
        params = {}
        time.sleep(0.2)   # be gentle with rate limits

    print()  # newline after the \r progress line
    return results


def build_params(args, fields: list) -> dict:
    params = {
        "access_token": args.token,
        "fields": ",".join(fields),
        "ad_type": args.ad_type,
        "ad_active_status": args.status,
        "limit": min(args.batch_size, 2000),
    }

    # Country targeting (required)
    params["ad_reached_countries"] = json.dumps(args.countries)

    # Search: keyword OR page IDs (mutually exclusive in practice)
    if args.search:
        params["search_terms"] = args.search
    if args.page_ids:
        params["search_page_ids"] = ",".join(str(p) for p in args.page_ids)

    # Optional filters
    if args.media_type and args.media_type != "ALL":
        params["media_type"] = args.media_type
    if args.platforms:
        params["publisher_platforms"] = json.dumps(args.platforms)
    if args.languages:
        params["languages"] = json.dumps(args.languages)
    if args.since:
        params["ad_delivery_date_min"] = args.since
    if args.until:
        params["ad_delivery_date_max"] = args.until

    return params


def fetch_ads(args) -> dict:
    if not args.search and not args.page_ids:
        raise ValueError("Provide at least --search or --page-ids.")

    # Try with extended fields first; fall back to basic if permission denied
    fields = BASIC_FIELDS + EXTENDED_FIELDS
    params = build_params(args, fields)

    print("Querying Meta Ad Library API...")
    try:
        ads = paginate(params, max_results=args.max_results)
    except RuntimeError as e:
        if "extended fields" in str(e).lower() or "200" in str(e):
            print("  Extended fields not available for this query; retrying with basic fields.")
            fields = BASIC_FIELDS
            params = build_params(args, fields)
            ads = paginate(params, max_results=args.max_results)
        else:
            raise

    print(f"Total ads fetched: {len(ads)}")

    return {
        "query": {
            "search_terms": args.search,
            "page_ids": args.page_ids,
            "countries": args.countries,
            "status": args.status,
            "ad_type": args.ad_type,
            "media_type": args.media_type,
            "platforms": args.platforms,
            "since": args.since,
            "until": args.until,
        },
        "total_ads": len(ads),
        "ads": ads,
    }


def main():
    parser = argparse.ArgumentParser(
        description="Fetch competitor ads from Meta Ad Library API.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )

    # Auth
    parser.add_argument("--token", required=True,
                        help="Meta user access token (from developers.facebook.com)")

    # Search targets
    parser.add_argument("--search", default=None,
                        help="Keyword(s) to search in ad copy, e.g. 'Nike shoes'")
    parser.add_argument("--page-ids", nargs="+", default=None,
                        help="One or more competitor Facebook Page IDs (max 10)")

    # Required filter
    parser.add_argument("--countries", nargs="+", default=["US"],
                        help="Country codes to scope the search, e.g. US GB AU (default: US)")

    # Optional filters
    parser.add_argument("--status", default="ALL",
                        choices=["ACTIVE", "INACTIVE", "ALL"],
                        help="Ad active status (default: ALL)")
    parser.add_argument("--ad-type", default="ALL",
                        choices=["ALL", "POLITICAL_AND_ISSUE_ADS", "HOUSING_ADS",
                                 "EMPLOYMENT_ADS", "FINANCIAL_PRODUCTS_ADS"],
                        help="Ad category type (default: ALL)")
    parser.add_argument("--media-type", default="ALL",
                        choices=["ALL", "IMAGE", "VIDEO", "MEME", "NONE"],
                        help="Filter by media type (default: ALL)")
    parser.add_argument("--platforms", nargs="+", default=None,
                        choices=["FACEBOOK", "INSTAGRAM", "AUDIENCE_NETWORK", "MESSENGER"],
                        help="Limit to specific platforms")
    parser.add_argument("--languages", nargs="+", default=None,
                        help="Filter by language codes, e.g. en es fr")
    parser.add_argument("--since", default=None,
                        help="Minimum ad delivery date YYYY-MM-DD")
    parser.add_argument("--until", default=None,
                        help="Maximum ad delivery date YYYY-MM-DD")

    # Pagination
    parser.add_argument("--max-results", type=int, default=0,
                        help="Stop after N results (0 = fetch everything, default: 0)")
    parser.add_argument("--batch-size", type=int, default=500,
                        help="Results per API page, max 2000 (default: 500)")

    # Output
    parser.add_argument("--output", default="meta_ads_output.json",
                        help="Output JSON file path (default: meta_ads_output.json)")

    args = parser.parse_args()

    try:
        result = fetch_ads(args)
    except requests.HTTPError as e:
        print(f"HTTP {e.response.status_code}: {e.response.text}", file=sys.stderr)
        sys.exit(1)
    except (RuntimeError, ValueError) as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)

    with open(args.output, "w", encoding="utf-8") as f:
        json.dump(result, f, indent=2, default=str)

    print(f"Saved to {args.output}")


if __name__ == "__main__":
    main()
