from django.conf import settings
from django.core.mail import send_mail
from django.core.mail import EmailMultiAlternatives
from django.utils.http import urlsafe_base64_encode
from django.utils.encoding import force_bytes
from django.contrib.auth.tokens import default_token_generator


def send_password_reset_email(user):
    try:
        uid = urlsafe_base64_encode(force_bytes(user.pk))
        token = default_token_generator.make_token(user)

        reset_link = f"{settings.BACKEND_URL}/api/auth/set-password/{uid}/{token}"

        subject = "Reset Your Password"

        text_content = f"""
        Hi {user.get_full_name()},

        We received a request to reset your password.
        Click the link below to reset it:
        {reset_link}

        This link expires in 24 hours.
        If you didn't request this, please ignore this email.

        Best regards,
        LandKeeper Support Team
        """

        html_content = f"""
        <!DOCTYPE html>
        <html lang="en">
        <body style="font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; background-color: #f4f6f9; margin: 0; padding: 40px 20px;">
            <div style="max-width: 600px; margin: auto; background: #ffffff; border-radius: 12px; overflow: hidden; box-shadow: 0 4px 20px rgba(0,0,0,0.08);">

                <div style="background: #2E7D32; padding: 40px 20px; text-align: center;">
                    <h1 style="color: #ffffff; font-size: 28px; font-weight: 700; margin: 0;">LandKeeper</h1>
                    <p style="color: #C8E6C9; font-size: 14px; margin-top: 6px;">Land Management CRM</p>
                </div>

                <div style="padding: 40px;">
                    <p style="font-size: 18px; font-weight: 600; color: #1a1a1a; margin-bottom: 16px;">
                        Hi {user.first_name or "there"},
                    </p>
                    <p style="font-size: 15px; color: #555; line-height: 1.7; margin-bottom: 32px;">
                        We received a request to reset the password for your LandKeeper account
                        associated with <strong>{user.email}</strong>.<br><br>
                        Click the button below to reset your password.
                        This link is valid for <strong>24 hours</strong>.
                    </p>

                    <div style="text-align: center; margin-bottom: 32px;">
                        <a href="{reset_link}"
                           style="display: inline-block; background: #2E7D32; color: #ffffff; text-decoration: none; padding: 14px 36px; border-radius: 8px; font-size: 15px; font-weight: 600;">
                            Reset My Password
                        </a>
                    </div>

                    <hr style="border: none; border-top: 1px solid #f0f0f0; margin: 32px 0;">

                    <p style="font-size: 13px; color: #888; line-height: 1.6;">
                        If the button doesn't work, copy and paste this link:<br>
                        <a href="{reset_link}" style="color: #2E7D32; word-break: break-all;">{reset_link}</a>
                    </p>

                    <div style="background: #FFF8E1; border-left: 4px solid #FFC107; padding: 14px 18px; border-radius: 6px; margin-top: 24px;">
                        <p style="font-size: 13px; color: #7a6200; line-height: 1.6;">
                            ⚠️ If you did not request a password reset, you can safely ignore this email.
                        </p>
                    </div>
                </div>

                <div style="background: #f9f9f9; padding: 24px 40px; text-align: center; border-top: 1px solid #f0f0f0;">
                    <p style="font-size: 12px; color: #aaa; line-height: 1.8; margin: 0;">
                        © 2026 LandKeeper. All rights reserved.<br>
                        This is an automated email, please do not reply.
                    </p>
                </div>

            </div>
        </body>
        </html>
        """

        email_message = EmailMultiAlternatives(
            subject=subject,
            body=text_content,
            from_email=settings.DEFAULT_FROM_EMAIL,
            to=[user.email],
        )
        email_message.attach_alternative(html_content, "text/html")
        email_message.send()
        return True

    except Exception as e:
        print(f"Email error: {e}")
        return False


def send_verification_email(user, code):
    subject = "Verify your email address"
    from_email = settings.DEFAULT_FROM_EMAIL
    recipient_list = [user.email]

    # Plain text fallback
    text_content = f"""
Hi {user.first_name},

Your verification code is: {code}

This code expires in 2 minutes.

If you did not register, please ignore this email.

© 2026 Your App. All rights reserved.
    """

    # HTML content
    html_content = f"""
<!DOCTYPE html>
<html>
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
</head>
<body style="margin:0; padding:0; background-color:#f4f6f9; font-family: Arial, sans-serif;">

    <table width="100%" cellpadding="0" cellspacing="0" style="background-color:#f4f6f9; padding: 40px 0;">
        <tr>
            <td align="center">
                <table width="500" cellpadding="0" cellspacing="0" style="background-color:#ffffff; border-radius:12px; overflow:hidden; box-shadow: 0 4px 20px rgba(0,0,0,0.08);">

                    <!-- Header -->
                    <tr>
                        <td align="center" style="background-color:#4F46E5; padding: 40px 30px;">
                            <h1 style="margin:0; color:#ffffff; font-size:26px; font-weight:700; letter-spacing:1px;">
                                ✉️ Email Verification
                            </h1>
                        </td>
                    </tr>

                    <!-- Body -->
                    <tr>
                        <td style="padding: 40px 40px 20px 40px;">
                            <p style="margin:0 0 10px 0; font-size:16px; color:#374151;">
                                Hi <strong>{user.first_name}</strong>,
                            </p>
                            <p style="margin:0 0 30px 0; font-size:15px; color:#6B7280; line-height:1.6;">
                                Thank you for registering! Please use the verification code below to activate your account.
                            </p>

                            <!-- Code Box -->
                            <table width="100%" cellpadding="0" cellspacing="0">
                                <tr>
                                    <td align="center">
                                        <div style="background-color:#F3F4F6; border: 2px dashed #4F46E5; border-radius:12px; padding: 24px 40px; display:inline-block;">
                                            <p style="margin:0 0 6px 0; font-size:12px; color:#9CA3AF; text-transform:uppercase; letter-spacing:2px;">
                                                Verification Code
                                            </p>
                                            <p style="margin:0; font-size:42px; font-weight:800; color:#4F46E5; letter-spacing:10px;">
                                                {code}
                                            </p>
                                        </div>
                                    </td>
                                </tr>
                            </table>

                            <!-- Expiry Notice -->
                            <table width="100%" cellpadding="0" cellspacing="0" style="margin-top:30px;">
                                <tr>
                                    <td style="background-color:#FEF3C7; border-left: 4px solid #F59E0B; border-radius:6px; padding:14px 18px;">
                                        <p style="margin:0; font-size:13px; color:#92400E;">
                                            <strong>This code expires in 10 minutes.</strong> Please verify your email promptly.
                                        </p>
                                    </td>
                                </tr>
                            </table>

                            <!-- Warning -->
                            <p style="margin:30px 0 0 0; font-size:13px; color:#9CA3AF; line-height:1.6;">
                                If you did not create an account, you can safely ignore this email. Someone may have entered your email address by mistake.
                            </p>
                        </td>
                    </tr>

                    <!-- Footer -->
                    <tr>
                        <td style="background-color:#F9FAFB; padding:24px 40px; border-top:1px solid #E5E7EB;">
                            <p style="margin:0; font-size:12px; color:#9CA3AF; text-align:center;">
                                © 2026 Your App. All rights reserved.<br>
                                <span style="color:#D1D5DB;">This is an automated email, please do not reply.</span>
                            </p>
                        </td>
                    </tr>

                </table>
            </td>
        </tr>
    </table>

</body>
</html>
    """

    email = EmailMultiAlternatives(subject, text_content, from_email, recipient_list)
    email.attach_alternative(html_content, "text/html")
    email.send(fail_silently=False)