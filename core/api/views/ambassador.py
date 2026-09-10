# from rest_framework.exceptions import NotFound, PermissionDenied
# from rest_framework.generics import (
#     CreateAPIView,
#     RetrieveAPIView,
#     ListAPIView,
# )
# from rest_framework.permissions import IsAuthenticated, AllowAny
# from rest_framework.response import Response
# from rest_framework.views import APIView

# from apps.referral.models import AmbassadorProfile, Referral, ReferralCommission
# from api.serializers.ambassador import (
#     AmbassadorRegistrationSerializer,
#     AmbassadorProfileSerializer,
#     ReferralInviteCreateSerializer,
#     ReferralAcceptSerializer,
#     ReferralListSerializer,
#     ReferralCommissionSerializer,
# )


# class AmbassadorRegistrationView(CreateAPIView):
#     serializer_class = AmbassadorRegistrationSerializer
#     permission_classes = [IsAuthenticated]


# class AmbassadorProfileView(RetrieveAPIView):
#     serializer_class = AmbassadorProfileSerializer
#     permission_classes = [IsAuthenticated]

#     def get_object(self):
#         try:
#             return self.request.user.ambassador_profile
#         except AmbassadorProfile.DoesNotExist:
#             raise NotFound("You are not registered as an ambassador.")


# class ReferralInviteCreateView(CreateAPIView):
#     serializer_class = ReferralInviteCreateSerializer
#     permission_classes = [IsAuthenticated]

#     def get_ambassador(self):
#         try:
#             return self.request.user.ambassador_profile
#         except AmbassadorProfile.DoesNotExist:
#             raise PermissionDenied(
#                 "You must be a registered ambassador to send referrals."
#             )

#     def get_serializer_context(self):
#         context = super().get_serializer_context()
#         context["ambassador"] = self.get_ambassador()
#         return context


# class ReferralListView(ListAPIView):
#     serializer_class = ReferralListSerializer
#     permission_classes = [IsAuthenticated]

#     def get_queryset(self):
#         try:
#             ambassador = self.request.user.ambassador_profile
#         except AmbassadorProfile.DoesNotExist:
#             raise PermissionDenied(
#                 "You must be a registered ambassador to view referrals."
#             )
#         return Referral.objects.filter(ambassador=ambassador).select_related(
#             "referred_organisation"
#         )


# class ReferralAcceptView(APIView):
#     permission_classes = [AllowAny]

#     def post(self, request, *args, **kwargs):
#         serializer = ReferralAcceptSerializer(data=request.data)
#         serializer.is_valid(raise_exception=True)
#         referral = serializer.save()
#         return Response(
#             ReferralAcceptSerializer(referral).data,
#             status=201,
#         )


# class ReferralCommissionListView(ListAPIView):
#     serializer_class = ReferralCommissionSerializer
#     permission_classes = [IsAuthenticated]

#     def get_queryset(self):
#         try:
#             ambassador = self.request.user.ambassador_profile
#         except AmbassadorProfile.DoesNotExist:
#             raise PermissionDenied(
#                 "You must be a registered ambassador to view commissions."
#             )
#         return ReferralCommission.objects.filter(
#             referral__ambassador=ambassador
#         ).select_related("referral__referred_organisation")
