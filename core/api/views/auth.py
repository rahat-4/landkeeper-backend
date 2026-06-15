from allauth.socialaccount.providers.google.views import GoogleOAuth2Adapter
from allauth.socialaccount.providers.oauth2.client import OAuth2Client
from dj_rest_auth.registration.views import SocialLoginView
from rest_framework.permissions import AllowAny
from dj_rest_auth.views import LoginView

class CustomLoginView(LoginView):
    permission_classes = [AllowAny]

class GoogleLoginView(SocialLoginView):
    adapter_class = GoogleOAuth2Adapter
    callback_url = "http://localhost:8000/auth/social/google/"
    client_class = OAuth2Client