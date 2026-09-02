"""
instagram_api.py — Instagram Graph API data pulls for the k_diesel_finds dashboard.

Uses the "Instagram API with Instagram Login" path (graph.instagram.com), matching
the standalone account setup already in place — no Facebook Page link required.

Permission set this app has (confirmed): instagram_business_basic,
instagram_business_manage_insights, instagram_business_manage_comments,
instagram_business_manage_messages, instagram_business_content_publish.
Only the first two are used here — this module is read-only (profile + insights).

IMPORTANT — metric names: Meta deprecated 'impressions' and 'profile_views' from
the Insights API in April 2025, replacing them with a unified 'views' metric.
This module uses 'views' and 'reach', not the old names. If Meta changes metric
names again, the error message from the API will name the invalid metric directly —
check that against the current Insights docs before guessing a fix.

Business Discovery and Hashtag Search are NOT available on this auth path — confirmed
by testing (they returned "nonexisting field" errors). Those require the Facebook
Login path with a Page-linked account, which this setup deliberately doesn't use.
"""

import requests
from typing import Optional

GRAPH_URL = "https://graph.instagram.com"
API_VERSION = "v26.0"


class InstagramAPIError(Exception):
    """Raised when the Instagram API returns an error response."""
    pass


def _get(path: str, token: str, params: Optional[dict] = None) -> dict:
    """Internal helper: GET request against the Instagram Graph API, raises on error."""
    url = f"{GRAPH_URL}/{API_VERSION}/{path}"
    query = {"access_token": token, **(params or {})}
    resp = requests.get(url, params=query, timeout=15)
    data = resp.json()
    if "error" in data:
        raise InstagramAPIError(data["error"].get("message", "Unknown Instagram API error"))
    return data


def get_profile_basic(token: str) -> dict:
    """
    Pull basic profile fields — id, username, followers_count.
    Requires: instagram_business_basic
    """
    return _get("me", token, {"fields": "id,username,followers_count"})


def get_account_insights(token: str, ig_user_id: str, period: str = "day") -> dict:
    """
    Pull account-level insights: reach and views over the given period.
    Requires: instagram_business_manage_insights

    Note: some account metrics don't populate for accounts under 100 followers —
    that's an Instagram limitation, not a bug here. An empty data set is expected
    in that case, not an error.
    """
    return _get(f"{ig_user_id}/insights", token, {
        "metric": "reach,views",
        "period": period,
    })


def get_recent_media(token: str, ig_user_id: str, limit: int = 25) -> dict:
    """
    Pull recent media objects (id, caption, media_type, timestamp, permalink).
    Requires: instagram_business_basic
    """
    return _get(f"{ig_user_id}/media", token, {
        "fields": "id,caption,media_type,timestamp,permalink",
        "limit": limit,
    })


def get_media_insights(token: str, media_id: str) -> dict:
    """
    Pull per-post insights: reach, views, likes, comments for one media object.
    Requires: instagram_business_manage_insights

    Note: valid metrics can differ slightly by media_type (e.g. Reels support
    additional metrics like plays/retention that feed posts don't). This uses
    the common subset that works across image/video/carousel posts.
    """
    return _get(f"{media_id}/insights", token, {
        "metric": "reach,views,likes,comments",
    })


def pull_and_flatten_account_snapshot(token: str, ig_user_id: str) -> dict:
    """
    Convenience function: pulls profile + account insights and flattens them
    into a single dict ready to hand to storage.save_ig_account_snapshot().
    Missing/unavailable metrics come back as None rather than raising, so a
    sub-100-follower account (where some metrics are unavailable) still saves
    a partial snapshot instead of failing outright.
    """
    profile = get_profile_basic(token)
    result = {
        "followers_count": profile.get("followers_count"),
        "reach": None,
        "views": None,
    }
    try:
        insights = get_account_insights(token, ig_user_id)
        for metric in insights.get("data", []):
            name = metric.get("name")
            values = metric.get("values", [])
            if name in result and values:
                result[name] = values[-1].get("value")
    except InstagramAPIError:
        # Insights unavailable (e.g. low follower count) — keep follower count only.
        pass
    return result
