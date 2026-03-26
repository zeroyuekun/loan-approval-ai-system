"""Two-Factor Authentication (TOTP) API views.

Provides endpoints for officer/admin users to enrol in TOTP-based 2FA,
verify OTP codes, and check their 2FA status. Customer accounts do not
require 2FA.
"""

import base64
import io

from django.conf import settings
from django_otp.plugins.otp_totp.models import TOTPDevice
from rest_framework import serializers, status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView


class TOTPSetupView(APIView):
    """Enrol the current user in TOTP 2FA. Returns a provisioning URI and QR code."""

    permission_classes = [IsAuthenticated]

    def post(self, request):
        user = request.user
        if user.role not in ('admin', 'officer'):
            return Response(
                {'detail': '2FA is only required for officer and admin accounts.'},
                status=status.HTTP_400_BAD_REQUEST,
            )

        # Create a new TOTP device (or return existing unconfirmed one)
        device, created = TOTPDevice.objects.get_or_create(
            user=user,
            name='default',
            defaults={'confirmed': False},
        )

        if device.confirmed:
            return Response(
                {'detail': '2FA is already enabled. Disable it first to re-enrol.'},
                status=status.HTTP_409_CONFLICT,
            )

        # Generate provisioning URI
        issuer = 'AussieLoanAI'
        uri = device.config_url

        # Generate QR code as base64 PNG
        qr_base64 = None
        try:
            import qrcode
            qr = qrcode.make(uri)
            buffer = io.BytesIO()
            qr.save(buffer, format='PNG')
            qr_base64 = base64.b64encode(buffer.getvalue()).decode()
        except ImportError:
            pass  # qrcode package optional for API-only use

        return Response({
            'provisioning_uri': uri,
            'qr_code_base64': qr_base64,
            'detail': 'Scan the QR code with your authenticator app, then verify with /2fa/verify/.',
        })


class TOTPVerifySerializer(serializers.Serializer):
    token = serializers.CharField(max_length=6, min_length=6)


class TOTPVerifyView(APIView):
    """Verify a TOTP code and confirm the device (completes 2FA enrolment)."""

    permission_classes = [IsAuthenticated]

    def post(self, request):
        ser = TOTPVerifySerializer(data=request.data)
        ser.is_valid(raise_exception=True)

        token = ser.validated_data['token']
        user = request.user

        device = TOTPDevice.objects.filter(user=user, name='default').first()
        if not device:
            return Response(
                {'detail': '2FA not set up. Call /2fa/setup/ first.'},
                status=status.HTTP_404_NOT_FOUND,
            )

        if device.verify_token(token):
            if not device.confirmed:
                device.confirmed = True
                device.save(update_fields=['confirmed'])
            return Response({'detail': '2FA verified successfully.', 'confirmed': True})

        return Response(
            {'detail': 'Invalid or expired token.'},
            status=status.HTTP_400_BAD_REQUEST,
        )


class TOTPStatusView(APIView):
    """Check whether the current user has 2FA enabled."""

    permission_classes = [IsAuthenticated]

    def get(self, request):
        user = request.user
        device = TOTPDevice.objects.filter(user=user, name='default', confirmed=True).first()
        required = user.role in ('admin', 'officer')
        return Response({
            'enabled': device is not None,
            'required': required,
        })


class TOTPDisableView(APIView):
    """Disable 2FA for the current user (requires valid OTP to confirm)."""

    permission_classes = [IsAuthenticated]

    def post(self, request):
        ser = TOTPVerifySerializer(data=request.data)
        ser.is_valid(raise_exception=True)

        token = ser.validated_data['token']
        user = request.user

        device = TOTPDevice.objects.filter(user=user, name='default', confirmed=True).first()
        if not device:
            return Response(
                {'detail': '2FA is not enabled.'},
                status=status.HTTP_404_NOT_FOUND,
            )

        if not device.verify_token(token):
            return Response(
                {'detail': 'Invalid token. Provide a valid OTP to disable 2FA.'},
                status=status.HTTP_400_BAD_REQUEST,
            )

        device.delete()
        return Response({'detail': '2FA has been disabled.'})
