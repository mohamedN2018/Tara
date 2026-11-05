#!/usr/bin/env bash
# Tara Intelligence WP 3.2: after the backfills, feed's read models match their
# owners. Both sides are counted back to back (the same minute), never against a
# fixed number: the dev data keeps growing while other agents run (04 section 0).
#
#   bash scripts/intel/check_backfill.sh           # dev stack (tara-postgres-1)
#   PG_CONTAINER=other-postgres bash scripts/intel/check_backfill.sh
#
# Criteria (04 WP 3.2):
#   intel_friend_edge (active)          = 2 x graph friendship (status accepted)
#   follow_edge (active)                = graph follow_relation (users and pages)
#   intel_group_membership (active)     = profile group_member (state active)
#   intel_page_ref                      = profile page
#   intel_content_ref (not deleted)     = post post (published or held, not deleted,
#                                         not removed: drafts and scheduled posts were
#                                         never announced and are visible to nobody)
#   author_ref (not active)             = identity account (deactivated or suspended)
#   graph account_ref (not active)      = identity account (deactivated or suspended)
#   intel_account_restriction (active)  = moderation users with a standing restrict/shadow
#   graph account_ref (restricted)      = the same moderation count
# Also reported, not criteria: groups and blocks.
set -euo pipefail
pg="${PG_CONTAINER:-tara-postgres-1}"
fail=0

q() {  # q <db> <sql>: one number
  docker exec "$pg" sh -c "psql -U \"\$POSTGRES_USER\" -d $1 -Atc \"$2\""
}

check() {  # check <name> <reader count> <owner count> [criterion|info]
  local name="$1" feed="$2" owner="$3" kind="${4:-criterion}"
  if [ "$feed" = "$owner" ]; then
    echo "ok   $name: reader $feed = owner $owner"
  elif [ "$kind" = info ]; then
    echo "info $name: reader $feed, owner $owner"
  else
    echo "FAIL $name: reader $feed != owner $owner"
    fail=1
  fi
}

echo "at $(date -u +%Y-%m-%dT%H:%M:%SZ)"
friends_owner=$(q graph_db "select 2 * count(*) from friendship where status = 'accepted'")
friends_feed=$(q feed_db "select count(*) from intel_friend_edge where active")
follows_owner=$(q graph_db "select count(*) from follow_relation")
follows_feed=$(q feed_db "select count(*) from follow_edge where active")
members_owner=$(q profile_db "select count(*) from group_member where state = 'active'")
members_feed=$(q feed_db "select count(*) from intel_group_membership where state = 'active'")
pages_owner=$(q profile_db "select count(*) from page")
pages_feed=$(q feed_db "select count(*) from intel_page_ref")
posts_owner=$(q post_db "select count(*) from post where deleted_at is null and state in ('published', 'held') and moderation_status <> 'removed'")
posts_feed=$(q feed_db "select count(*) from intel_content_ref where state <> 'deleted'")
groups_owner=$(q profile_db "select count(*) from social_group")
groups_feed=$(q feed_db "select count(*) from intel_group_ref")
blocks_owner=$(q graph_db "select count(*) from block_relation")
blocks_feed=$(q feed_db "select count(*) filter (where low_blocks) + count(*) filter (where high_blocks) from intel_block_pair")
inactive_owner=$(q identity_db "select count(*) from account where status in ('deactivated', 'suspended')")
inactive_feed=$(q feed_db "select count(*) from author_ref where not active")
inactive_graph=$(q graph_db "select count(*) from account_ref where not active")
# A user case decided restrict/shadow (its latest action) that no appeal overturned.
restricted_owner=$(q moderation_db "select count(distinct c.target_id) from moderation_case c where c.target_type = 'user' and (select a.action from moderation_action a where a.case_id = c.id order by a.created_at desc, a.id desc limit 1) in ('restrict', 'shadow') and not exists (select 1 from appeal p where p.case_id = c.id and p.status = 'overturned')")
restricted_feed=$(q feed_db "select count(*) from intel_account_restriction where active")
restricted_graph=$(q graph_db "select count(*) from account_ref where restriction <> ''")
echo "until $(date -u +%Y-%m-%dT%H:%M:%SZ)"

check "friend edges (2 x accepted friendships)" "$friends_feed" "$friends_owner"
check "follow edges" "$follows_feed" "$follows_owner"
check "active group memberships" "$members_feed" "$members_owner"
check "pages" "$pages_feed" "$pages_owner"
check "content refs (published posts)" "$posts_feed" "$posts_owner"
check "inactive authors (feed author_ref)" "$inactive_feed" "$inactive_owner"
check "inactive accounts (graph account_ref)" "$inactive_graph" "$inactive_owner"
check "restricted accounts (feed)" "$restricted_feed" "$restricted_owner"
check "restricted accounts (graph)" "$restricted_graph" "$restricted_owner"
check "groups" "$groups_feed" "$groups_owner" info
check "block directions" "$blocks_feed" "$blocks_owner" info
exit "$fail"
