from tara_common.permissions import HasCapability

# Kept for importers from before the capability registry (8.12): the reviewer
# check is now the ``ads.review`` capability, which ad_reviewer and admin hold
# by default, exactly as the old role check allowed.
IsAdReviewer = HasCapability("ads.review")
