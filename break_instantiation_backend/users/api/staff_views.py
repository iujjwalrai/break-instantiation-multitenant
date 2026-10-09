from django.contrib.auth import authenticate
from django.contrib.auth import login
from django.contrib.auth import logout
from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError as DjangoValidationError
from django.middleware.csrf import get_token
from rest_framework import serializers
from rest_framework import status
from rest_framework.authentication import SessionAuthentication
from rest_framework.permissions import AllowAny
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from break_instantiation_backend.users.models import User
from break_instantiation_backend.users.roles import StaffRole
from break_instantiation_backend.users.roles import is_staff_member
from break_instantiation_backend.users.roles import is_super_admin

from .permissions import IsStaffMember
from .permissions import IsSuperAdmin


def staff_payload(user: User) -> dict:
    role = StaffRole.SUPER_ADMIN if is_super_admin(user) else user.role
    return {
        "id": user.id,
        "email": user.email,
        "name": user.name,
        "role": role,
    }


class StaffLoginSerializer(serializers.Serializer):
    email = serializers.EmailField()
    password = serializers.CharField(trim_whitespace=False)


class StaffAdminCreateSerializer(serializers.Serializer):
    email = serializers.EmailField()
    name = serializers.CharField(max_length=255, allow_blank=True, required=False)
    password = serializers.CharField(trim_whitespace=False)

    def validate_email(self, value: str) -> str:
        if User.objects.filter(email__iexact=value).exists():
            msg = "A user with this email already exists."
            raise serializers.ValidationError(msg)
        return value

    def validate_password(self, value: str) -> str:
        email = ""
        if hasattr(self, "initial_data"):
            email = self.initial_data.get("email") or ""
        try:
            validate_password(value, user=User(email=email))
        except DjangoValidationError as exc:
            raise serializers.ValidationError(list(exc.messages)) from exc
        return value


class StaffLoginView(APIView):
    authentication_classes = []
    permission_classes = [AllowAny]

    def post(self, request):
        serializer = StaffLoginSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        user = authenticate(
            request,
            email=serializer.validated_data["email"],
            password=serializer.validated_data["password"],
        )
        if user is None or not is_staff_member(user):
            return Response(
                {"detail": "Invalid email or password."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        login(request, user)
        get_token(request)
        return Response(staff_payload(user))


class StaffLogoutView(APIView):
    authentication_classes = [SessionAuthentication]
    permission_classes = [IsAuthenticated]

    def post(self, request):
        logout(request)
        return Response(status=status.HTTP_204_NO_CONTENT)


class StaffMeView(APIView):
    authentication_classes = [SessionAuthentication]
    permission_classes = [IsAuthenticated, IsStaffMember]

    def get(self, request):
        return Response(staff_payload(request.user))


class StaffAdminListCreateView(APIView):
    """Super admin creates and lists the admins who own clients."""

    authentication_classes = [SessionAuthentication]
    permission_classes = [IsAuthenticated, IsSuperAdmin]

    def get(self, request):
        admins = User.objects.filter(role=StaffRole.ADMIN).order_by("email")
        return Response(
            [
                {
                    "id": admin.id,
                    "email": admin.email,
                    "name": admin.name,
                    "role": admin.role,
                }
                for admin in admins
            ],
        )

    def post(self, request):
        serializer = StaffAdminCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        user = User.objects.create_user(
            email=serializer.validated_data["email"],
            password=serializer.validated_data["password"],
            name=serializer.validated_data.get("name", ""),
            role=StaffRole.ADMIN,
        )
        return Response(staff_payload(user), status=status.HTTP_201_CREATED)
