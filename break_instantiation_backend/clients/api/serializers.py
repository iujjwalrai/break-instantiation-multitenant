from rest_framework import serializers

from break_instantiation_backend.clients.models import Client


class ClientSerializer(serializers.ModelSerializer[Client]):
    has_login = serializers.SerializerMethodField()
    portal_invite_status = serializers.SerializerMethodField()
    consent_granted_at = serializers.SerializerMethodField()

    class Meta:
        model = Client
        fields = [
            "id",
            "full_name",
            "email",
            "has_login",
            "portal_invite_status",
            "consent_granted_at",
        ]
        read_only_fields = fields

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

    def get_consent_granted_at(self, obj: Client):
        """When the current consent was first stored.

        `None` when the client has not granted consent, or staff withdrew
        it. A later reinstate keeps the original `created_at`.
        """
        record = getattr(obj, "consent_record", None)
        if record is None or record.withdrawn_at is not None:
            return None
        return record.created_at


class ClientCreateSerializer(serializers.ModelSerializer[Client]):
    class Meta:
        model = Client
        fields = ["full_name", "email"]

    def validate_email(self, value: str) -> str:
        if Client.objects.filter(email__iexact=value).exists():
            msg = "A client with this email already exists."
            raise serializers.ValidationError(msg)
        return value


class ClientUpdateSerializer(serializers.ModelSerializer[Client]):
    """Name and email a staff member can change after the row exists."""

    class Meta:
        model = Client
        fields = ["full_name", "email"]

    def validate_email(self, value: str) -> str:
        existing = Client.objects.filter(email__iexact=value)
        if self.instance is not None:
            existing = existing.exclude(pk=self.instance.pk)
        if existing.exists():
            msg = "A client with this email already exists."
            raise serializers.ValidationError(msg)
        return value
