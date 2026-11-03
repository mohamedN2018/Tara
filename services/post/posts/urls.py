from django.urls import path

from . import views

app_name = "posts"

urlpatterns = [
    path("posts/", views.PostCreateView.as_view(), name="post-create"),
    path("posts/batch/", views.PostBatchView.as_view(), name="post-batch"),
    path("posts/<uuid:post_id>/", views.PostDetailView.as_view(), name="post-detail"),
    path("posts/<uuid:post_id>/reactions/", views.ReactionView.as_view(), name="post-reactions"),
    path("posts/<uuid:post_id>/comments/", views.CommentsView.as_view(), name="post-comments"),
    path("posts/<uuid:post_id>/share/", views.ShareView.as_view(), name="post-share"),
    path("posts/<uuid:post_id>/shares/", views.SharesView.as_view(), name="post-shares"),
    path("posts/<uuid:post_id>/vote/", views.VoteView.as_view(), name="post-vote"),
    path("posts/<uuid:post_id>/save/", views.SaveView.as_view(), name="post-save"),
    path("posts/<uuid:post_id>/report/", views.ReportView.as_view(), name="post-report"),
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
