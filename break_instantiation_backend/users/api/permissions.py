from rest_framework.permissions import BasePermission

from break_instantiation_backend.users.roles import can_sign_in
from break_instantiation_backend.users.roles import is_super_admin
from break_instantiation_backend.users.roles import is_tenant_staff


class IsTenantStaff(BasePermission):
    """Admin or super admin of this child. A backend admin does not pass."""

    def has_permission(self, request, view) -> bool:
        return is_tenant_staff(request.user)


class CanSignIn(BasePermission):
    """Tenant staff or a backend admin."""

    def has_permission(self, request, view) -> bool:
        return can_sign_in(request.user)


class IsSuperAdmin(BasePermission):
    def has_permission(self, request, view) -> bool:
        return is_super_admin(request.user)
