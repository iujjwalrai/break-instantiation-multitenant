from rest_framework.permissions import BasePermission

from break_instantiation_backend.users.roles import is_staff_member
from break_instantiation_backend.users.roles import is_super_admin


class IsStaffMember(BasePermission):
    """Admin or super admin. A client session does not pass."""

    def has_permission(self, request, view) -> bool:
        return is_staff_member(request.user)


class IsSuperAdmin(BasePermission):
    def has_permission(self, request, view) -> bool:
        return is_super_admin(request.user)
