from rest_framework import serializers

from break_instantiation_backend.clients.models import Client
from break_instantiation_backend.users.models import User
from break_instantiation_backend.users.roles import StaffRole
from break_instantiation_backend.users.roles import is_super_admin


class ClientSerializer(serializers.ModelSerializer[Client]):
    admin_email = serializers.SerializerMethodField()
    has_login = serializers.SerializerMethodField()
    portal_invite_status = serializers.SerializerMethodField()

    class Meta:
        model = Client
        fields = [
            "id",
            "full_name",
            "email",
            "admin",
            "admin_email",
            "has_login",
            "portal_invite_status",
        ]
        read_only_fields = fields

    def get_admin_email(self, obj: Client) -> str | None:
        if obj.admin_id is None:
            return None
        return obj.admin.email

    def get_has_login(self, obj: Client) -> bool:
        return obj.client_user_id is not None

    def get_portal_invite_status(self, obj: Client) -> str | None:
        prefetched = getattr(obj, "_prefetched_objects_cache", {})
        if "portal_invites" in prefetched:
            invites = list(obj.portal_invites.all())
            latest = invites[0] if invites else None
        else:
            latest = obj.portal_invites.order_by("-created").first()
        if latest is None:
            return None
        return latest.status


class ClientCreateSerializer(serializers.ModelSerializer[Client]):
    admin = serializers.PrimaryKeyRelatedField(
        queryset=User.objects.filter(role=StaffRole.ADMIN),
        required=False,
        allow_null=True,
    )

    class Meta:
        model = Client
        fields = ["full_name", "email", "admin"]

    def validate_email(self, value: str) -> str:
        if Client.objects.filter(email__iexact=value).exists():
            msg = "A client with this email already exists."
            raise serializers.ValidationError(msg)
        return value

    def validate(self, attrs):
        request = self.context["request"]
        if is_super_admin(request.user):
            return attrs
        if "admin" in self.initial_data:
            msg = "Only a super admin assigns the responsible admin."
            raise serializers.ValidationError({"admin": msg})
        attrs["admin"] = request.user
        return attrs
