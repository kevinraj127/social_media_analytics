"""
app.py — Bytes on Disc / k_diesel_finds channel analytics dashboard.

Layout: a benchmark-gauge summary at top, then per-channel tabs.
- Instagram: live pull via Graph API, snapshotted locally (this file, working now)
- eBay: placeholder — wire in the existing ebay_movie_insights_oop.py Browse API
  logic here; that channel doesn't need snapshotting since eBay's API isn't
  retention-limited the way Instagram's is
- Substack: manual CSV upload, since there's no public API for this channel

Secrets needed (add via Streamlit's secrets.toml or the Cloud secrets UI):
    IG_ACCESS_TOKEN = "..."
    IG_USER_ID = "..."
"""

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

st.set_page_config(page_title="Bytes on Disc — Channel Dashboard", layout="wide")
storage.init_db()

st.title("Bytes on Disc — Channel Dashboard")

# ---------------------------------------------------------------------------
# Benchmark summary row
# ---------------------------------------------------------------------------
st.subheader("Progress toward channel benchmarks")

latest_ig = storage.get_latest_ig_snapshot()
latest_substack = storage.get_latest_substack_snapshot()

col1, col2, col3 = st.columns(3)

with col1:
    st.markdown("**Instagram — 1,000 followers**")
    current_followers = latest_ig["followers_count"] if latest_ig else 0
    st.progress(min(current_followers / IG_FOLLOWER_TARGET, 1.0))
    st.caption(f"{current_followers:,} / {IG_FOLLOWER_TARGET:,} followers"
               if latest_ig else "No Instagram snapshot yet — visit the Instagram tab.")

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

with col3:
    st.markdown("**eBay — active listing health**")
    st.caption("Wire in existing Browse API pull here (live, not snapshotted).")

st.divider()

# ---------------------------------------------------------------------------
# Tabs
# ---------------------------------------------------------------------------
tab_ig, tab_ebay, tab_substack = st.tabs(["Instagram", "eBay", "Substack"])

with tab_ig:
    st.header("Instagram")

    if "IG_ACCESS_TOKEN" not in st.secrets or "IG_USER_ID" not in st.secrets:
        st.warning(
            "Add IG_ACCESS_TOKEN and IG_USER_ID to your Streamlit secrets to pull live data. "
            "Until then, this tab will only show previously saved snapshots."
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

    # Follower trend chart
    history = storage.get_ig_account_history()
    if history:
        df = pd.DataFrame([dict(row) for row in history])
        st.subheader("Follower trend")
        st.line_chart(df.set_index("snapshot_date")["followers_count"])
    else:
        st.info("No history yet — click 'Pull latest Instagram data' above to start tracking.")

    # Recent post performance table
    media_rows = storage.get_ig_media_history(limit=25)
    if media_rows:
        st.subheader("Recent post performance")
        media_df = pd.DataFrame([dict(row) for row in media_rows])
        st.dataframe(
            media_df[["timestamp", "caption_preview", "media_type", "reach", "likes", "comments"]],
            use_container_width=True,
        )

with tab_ebay:
    st.header("eBay")
    st.info(
        "Not yet wired up. Pull this from the existing Browse API logic in "
        "ebay_movie_insights_oop.py — active listings, views, watchers. "
        "This tab should call the API live on each visit rather than snapshotting, "
        "since eBay's data isn't retention-limited like Instagram's insights are."
    )

with tab_substack:
    st.header("Substack")
    st.write("Substack has no public API — upload a stats CSV export to log a snapshot.")

    uploaded = st.file_uploader("Upload Substack CSV export", type="csv")
    if uploaded is not None:
        sub_df = pd.read_csv(uploaded)
        st.write("Preview:")
        st.dataframe(sub_df.head())
        st.warning(
            "Column mapping not yet wired up — once you share a sample export, "
            "this can auto-map to total/free/paid subscribers and open rate."
        )

    substack_history = storage.get_substack_history()
    if substack_history:
        st.subheader("Subscriber trend")
        sub_hist_df = pd.DataFrame([dict(row) for row in substack_history])
        st.line_chart(sub_hist_df.set_index("snapshot_date")["total_subscribers"])
