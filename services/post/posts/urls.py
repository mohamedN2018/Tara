from django.urls import path, re_path

from . import group_views, views

app_name = "posts"

urlpatterns = [
    path("posts/", views.PostCreateView.as_view(), name="post-create"),
    path("posts/batch/", views.PostBatchView.as_view(), name="post-batch"),
    # The composer (2C): the author's drafts and scheduled posts, and tag settings.
    path("posts/drafts/", views.DraftsView.as_view(), name="drafts"),
    path("posts/drafts/<uuid:post_id>/", views.DraftDetailView.as_view(), name="draft-detail"),
    path(
        "posts/drafts/<uuid:post_id>/publish/",
        views.DraftPublishView.as_view(),
        name="draft-publish",
    ),
    path("posts/settings/", views.PostSettingsView.as_view(), name="post-settings"),
    # Groups (1.11): the group itself lives in profile under /api/v1/groups/.
    path("posts/groups/<uuid:group_id>/", group_views.GroupFeedView.as_view(), name="group-feed"),
    path(
        "posts/groups/<uuid:group_id>/reports/",
        group_views.GroupReportsView.as_view(),
        name="group-reports",
    ),
    path(
        "posts/groups/<uuid:group_id>/reports/dismiss/",
        group_views.GroupReportDismissView.as_view(),
        name="group-report-dismiss",
    ),
    re_path(
        r"^posts/(?P<post_id>[0-9a-fA-F-]{36})/(?P<action>approve|decline)/$",
        group_views.GroupPostApprovalView.as_view(),
        name="group-post-approval",
    ),
    path("posts/<uuid:post_id>/pin/", group_views.GroupPostPinView.as_view(), name="post-pin"),
    path("posts/<uuid:post_id>/", views.PostDetailView.as_view(), name="post-detail"),
    path("posts/<uuid:post_id>/reactions/", views.ReactionView.as_view(), name="post-reactions"),
    path("posts/<uuid:post_id>/comments/", views.CommentsView.as_view(), name="post-comments"),
    path("posts/<uuid:post_id>/share/", views.ShareView.as_view(), name="post-share"),
    path("posts/<uuid:post_id>/shares/", views.SharesView.as_view(), name="post-shares"),
    path("posts/<uuid:post_id>/vote/", views.VoteView.as_view(), name="post-vote"),
    path("posts/<uuid:post_id>/save/", views.SaveView.as_view(), name="post-save"),
    path("posts/<uuid:post_id>/report/", views.ReportView.as_view(), name="post-report"),
    path("posts/<uuid:post_id>/tags/me/", views.MyTagView.as_view(), name="post-my-tag"),
    path("comments/<uuid:comment_id>/", views.CommentDetailView.as_view(), name="comment-detail"),
    path(
        "comments/<uuid:comment_id>/replies/", views.RepliesView.as_view(), name="comment-replies"
    ),
    path(
        "comments/<uuid:comment_id>/reactions/",
        views.CommentReactionView.as_view(),
        name="comment-reactions",
    ),
    path(
        "comments/<uuid:comment_id>/report/",
        views.CommentReportView.as_view(),
        name="comment-report",
    ),
    path("saved/", views.SavedListView.as_view(), name="saved-list"),
]
