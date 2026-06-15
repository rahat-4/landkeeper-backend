from dj_rest_auth.serializers import LoginSerializer, JWTSerializer
from rest_framework import serializers
from django.contrib.auth import get_user_model
User = get_user_model()

class CustomLoginSerializer(LoginSerializer):
    username = None
    email = serializers.EmailField(required=True)
    password = serializers.CharField(write_only=True)

class UserSerializer(serializers.ModelSerializer):
    password = serializers.CharField(write_only=True, min_length=8, required=False)

    class Meta:
        model = User
        fields = [
            "alias",
            "email",
            "password",
            "title",
            "first_name",
            "middle_name",
            "last_name",
            "role",
            "phone",
            "profile_image",
            "city",
            "state",
            "country",
            "post_code",
            "address",
            "is_active",
            "created_at",
            "updated_at",
        ]
        read_only_fields = ["alias", "created_at", "updated_at"]

    def validate(self, attrs):
        if self.instance is None and not attrs.get("password"):
            raise serializers.ValidationError({"password": "This field is required."})
        return attrs

    def create(self, validated_data):
        password = validated_data.pop("password")
        user = User(**validated_data)
        user.set_password(password)
        user.is_password_set = True
        user.save()
        return user

    def update(self, instance, validated_data):
        password = validated_data.pop("password", None)
        if password:
            instance.set_password(password)
            instance.is_password_set = True
        for attr, value in validated_data.items():
            setattr(instance, attr, value)
        instance.save()
        return instance

class CustomJWTSerializer(JWTSerializer):
    user = UserSerializer(read_only=True)