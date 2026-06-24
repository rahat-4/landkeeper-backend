from django.conf import settings
from django.core.mail import EmailMultiAlternatives
from django.utils.http import urlsafe_base64_encode
from django.utils.encoding import force_bytes
from django.contrib.auth.tokens import default_token_generator


def send_password_reset_email(user):
    try:
        uid = urlsafe_base64_encode(force_bytes(user.pk))
        token = default_token_generator.make_token(user)

        reset_link = f"{settings.BACKEND_URL}/api/auth/forgot-password/{uid}/{token}"

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