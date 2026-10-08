from rest_framework import serializers


class MagicLoginRequestSerializer(serializers.Serializer):
    email = serializers.EmailField()


class MagicLoginRedeemSerializer(serializers.Serializer):
    token = serializers.CharField()
