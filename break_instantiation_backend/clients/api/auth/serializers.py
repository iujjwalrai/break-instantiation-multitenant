from rest_framework import serializers


class PortalInviteRedeemSerializer(serializers.Serializer):
    token = serializers.CharField()


class MagicLoginRequestSerializer(serializers.Serializer):
    email = serializers.EmailField()


class MagicLoginRedeemSerializer(serializers.Serializer):
    token = serializers.CharField()
