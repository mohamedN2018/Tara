from tara_common.permissions import HasAnyRole


class IsAdReviewer(HasAnyRole):
    required_roles = {"ad_reviewer", "admin"}
