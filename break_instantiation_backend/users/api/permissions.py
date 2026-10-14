from rest_framework.permissions import BasePermission

from break_instantiation_backend.users.roles import can_sign_in


class IsTenantStaff(BasePermission):
    """Customer admin or backend admin.

    An admin manages every client and the other admin accounts in this child.
    A backend admin uses the same tools and is not a tenant user.
    """

    def has_permission(self, request, view) -> bool:
        return can_sign_in(request.user)


class CanSignIn(BasePermission):
    """Customer admin or backend admin."""

    def has_permission(self, request, view) -> bool:
        return can_sign_in(request.user)
