"""
app.py — k_diesel_finds channel analytics dashboard.

Scope: Instagram (live pull, percentage-to-goal) and Substack (manual CSV
upload). eBay was intentionally dropped from this dashboard — not tracked here.

Note on persistence: this app runs on Streamlit Community Cloud, where local
SQLite storage is wiped on restarts/redeploys. Given that, this version keeps
things simple — it shows a live percentage toward the follower goal rather than
a historical trend chart, since a trend chart would be misleading if the
underlying history can silently reset. The recent-post performance table below
still uses local storage for convenience within a session, but don't rely on
it persisting long-term until a hosted database is wired in.

Secrets needed (add via Streamlit's secrets.toml or the Cloud secrets UI):
    IG_ACCESS_TOKEN = "..."
    IG_USER_ID = "..."
"""

from datetime import datetime
from zoneinfo import ZoneInfo

import streamlit as st
import pandas as pd

import storage
from instagram_api import (
    pull_and_flatten_account_snapshot,
    get_recent_media,
    get_media_insights,
    InstagramAPIError,
)

# --- Benchmarks (adjust as targets change) ---
IG_FOLLOWER_TARGET = 1000


def to_central(ts_str: str) -> str:
    """
    Convert an Instagram timestamp (ISO 8601, UTC) to a readable Central time string.
    Used for display only — the raw ISO string stays in the database so sorting
    by timestamp isn't affected by the display timezone.
    """
    if not ts_str:
        return ""
    try:
        dt = datetime.fromisoformat(ts_str.replace("Z", "+00:00"))
        central_dt = dt.astimezone(ZoneInfo("America/Chicago"))
        return central_dt.strftime("%Y-%m-%d %H:%M:%S %Z")
    except ValueError:
        return ts_str  # fall back to raw string if the format is unexpected


st.set_page_config(page_title="Bytes on Disc — Channel Dashboard", layout="wide")
storage.init_db()

st.title("k_diesel_finds — Brand Channel Dashboard")

# ---------------------------------------------------------------------------
# Benchmark summary row
# ---------------------------------------------------------------------------
st.subheader("Progress toward channel benchmarks")

latest_ig = storage.get_latest_ig_snapshot()
latest_substack = storage.get_latest_substack_snapshot()

col1, col2 = st.columns(2)

with col1:
    st.markdown("**Instagram — 1,000 followers**")
    current_followers = latest_ig["followers_count"] if latest_ig else 0
    pct = (current_followers / IG_FOLLOWER_TARGET) * 100
    if latest_ig:
        st.metric("Progress to goal", f"{pct:.1f}%", f"{current_followers:,} followers")
    else:
        st.caption("No Instagram data yet — visit the Instagram tab and pull latest data.")

with col2:
    st.markdown("**Substack — engagement checkpoint**")
    st.caption("Set your own target once you've decided the trigger metric "
               "(e.g. free subscribers + open rate combined).")
    if latest_substack:
        st.caption(f"Latest: {latest_substack['total_subscribers']:,} subscribers, "
                   f"{latest_substack['open_rate']}% open rate"
                   if latest_substack['open_rate'] else
                   f"Latest: {latest_substack['total_subscribers']:,} subscribers")
    else:
        st.caption("No Substack snapshot yet — upload a CSV export on the Substack tab.")

st.divider()

# ---------------------------------------------------------------------------
# Tabs
# ---------------------------------------------------------------------------
tab_ig, tab_substack = st.tabs(["Instagram", "Substack"])

with tab_ig:
    st.header("Instagram")

    if "IG_ACCESS_TOKEN" not in st.secrets or "IG_USER_ID" not in st.secrets:
        st.warning(
            "Add IG_ACCESS_TOKEN and IG_USER_ID to your Streamlit secrets to pull live data."
        )
    else:
        if st.button("Pull latest Instagram data"):
            token = st.secrets["IG_ACCESS_TOKEN"]
            ig_user_id = st.secrets["IG_USER_ID"]
            try:
                # Account-level snapshot
                snapshot = pull_and_flatten_account_snapshot(token, ig_user_id)
                storage.save_ig_account_snapshot(
                    followers_count=snapshot["followers_count"],
                    reach=snapshot["reach"],
                    views=snapshot["views"],
                )

                # Per-post snapshots for recent media
                media = get_recent_media(token, ig_user_id, limit=25)
                for post in media.get("data", []):
                    try:
                        post_insights = get_media_insights(token, post["id"])
                        metrics = {m["name"]: m["values"][0]["value"]
                                   for m in post_insights.get("data", []) if m.get("values")}
                    except InstagramAPIError:
                        metrics = {}
                    storage.save_ig_media_snapshot(
                        media_id=post["id"],
                        caption_preview=(post.get("caption") or "")[:80],
                        media_type=post.get("media_type", ""),
                        timestamp=post.get("timestamp", ""),
                        permalink=post.get("permalink", ""),
                        engagement=metrics.get("reach"),  # 'engagement' metric retired; using reach as proxy
                        reach=metrics.get("reach"),
                        likes=metrics.get("likes"),
                        comments=metrics.get("comments"),
                    )
                st.success("Pulled and saved latest Instagram data.")
                st.rerun()
            except InstagramAPIError as e:
                st.error(f"Instagram API error: {e}")

    # Recent post performance table
    media_rows = storage.get_ig_media_history(limit=25)
    if media_rows:
        st.subheader("Recent post performance")
        media_df = pd.DataFrame([dict(row) for row in media_rows])
        media_df["timestamp"] = media_df["timestamp"].apply(to_central)
        st.dataframe(
            media_df[["timestamp", "caption_preview", "media_type", "reach", "likes", "comments"]],
            use_container_width=True,
        )
    else:
        st.info("No post data yet — click 'Pull latest Instagram data' above.")

with tab_substack:
    st.header("Substack")
    st.write("Substack has no public API — upload a stats CSV export to log subscriber history.")

    uploaded = st.file_uploader("Upload Substack CSV export", type="csv")
    if uploaded is not None:
        # Substack's subscriber export has no header row: date, subscriber count.
        # Date format is YYYY/MM/DD; the count is the running total for that day.
        sub_df = pd.read_csv(uploaded, header=None, names=["date", "total_subscribers"])
        sub_df["date"] = pd.to_datetime(sub_df["date"], format="%Y/%m/%d").dt.strftime("%Y-%m-%d")

        for _, row in sub_df.iterrows():
            storage.save_substack_snapshot(
                total_subscribers=int(row["total_subscribers"]),
                snapshot_date=row["date"],
            )
        st.success(f"Loaded {len(sub_df)} days of subscriber history.")
        st.rerun()

    substack_history = storage.get_substack_history()
    if substack_history:
        st.subheader("Subscriber count over time")
        sub_hist_df = pd.DataFrame([dict(row) for row in substack_history])
        st.line_chart(sub_hist_df.set_index("snapshot_date")["total_subscribers"])
    else:
        st.info("Upload a CSV export above to see subscriber history.")
