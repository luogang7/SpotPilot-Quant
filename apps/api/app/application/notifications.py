import smtplib
from collections.abc import Callable
from email.message import EmailMessage

import httpx

from app.core.config import Settings
from app.domain.models import NotificationProvider, NotificationResult, NotificationTestRequest


class NotificationService:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self._senders: dict[NotificationProvider, Callable[[NotificationTestRequest], NotificationResult]] = {
            NotificationProvider.FEISHU: self._send_feishu,
            NotificationProvider.WECOM: self._send_wecom,
            NotificationProvider.TELEGRAM: self._send_telegram,
            NotificationProvider.EMAIL: self._send_email,
            NotificationProvider.SLACK: self._send_slack,
            NotificationProvider.DISCORD: self._send_discord,
        }

    def configured_channels(self) -> dict[str, bool | int | str]:
        return {
            "feishu_webhook": bool(self.settings.feishu_webhook_url),
            "wecom_webhook": bool(self.settings.wecom_webhook_url),
            "telegram_bot_token": bool(self.settings.telegram_bot_token),
            "telegram_chat_id": bool(self.settings.telegram_chat_id),
            "telegram_bot": bool(self.settings.telegram_bot_token and self.settings.telegram_chat_id),
            "email_smtp_host": bool(self.settings.email_smtp_host),
            "email_smtp_port": self.settings.email_smtp_port,
            "email_smtp_username": bool(self.settings.email_smtp_username),
            "email_smtp_password": bool(self.settings.email_smtp_password),
            "email_from": bool(self.settings.email_from),
            "email_to": bool(self.settings.email_to),
            "email_use_tls": self.settings.email_use_tls,
            "email_smtp": bool(
                self.settings.email_smtp_host
                and self.settings.email_from
                and self.settings.email_to
            ),
            "slack_webhook": bool(self.settings.slack_webhook_url),
            "discord_webhook": bool(self.settings.discord_webhook_url),
            "severity": "warning+",
        }

    def send_test(self, request: NotificationTestRequest) -> NotificationResult:
        provider = NotificationProvider(request.provider)
        sender = self._senders.get(provider)
        if sender is None:
            return NotificationResult(
                success=False,
                provider=provider.value,
                message=f"{provider.value} notification provider is not supported",
            )
        return sender(request)

    def send_to_configured_channels(
        self,
        title: str,
        message: str,
        timeout_seconds: int = 10,
    ) -> list[NotificationResult]:
        providers = self._configured_providers()
        if not providers:
            return [
                NotificationResult(
                    success=False,
                    provider="all",
                    message="no notification channels configured",
                ),
            ]

        return [
            self.send_test(
                NotificationTestRequest(
                    provider=provider,
                    title=title,
                    message=message,
                    timeout_seconds=timeout_seconds,
                ),
            )
            for provider in providers
        ]

    def _configured_providers(self) -> list[NotificationProvider]:
        providers: list[NotificationProvider] = []
        if self.settings.feishu_webhook_url:
            providers.append(NotificationProvider.FEISHU)
        if self.settings.wecom_webhook_url:
            providers.append(NotificationProvider.WECOM)
        if self.settings.telegram_bot_token and self.settings.telegram_chat_id:
            providers.append(NotificationProvider.TELEGRAM)
        if self.settings.email_smtp_host and self.settings.email_from and self.settings.email_to:
            providers.append(NotificationProvider.EMAIL)
        if self.settings.slack_webhook_url:
            providers.append(NotificationProvider.SLACK)
        if self.settings.discord_webhook_url:
            providers.append(NotificationProvider.DISCORD)
        return providers

    def _send_feishu(self, request: NotificationTestRequest) -> NotificationResult:
        if not self.settings.feishu_webhook_url:
            return self._not_configured(NotificationProvider.FEISHU, "FEISHU_WEBHOOK_URL")

        payload = {"msg_type": "text", "content": {"text": self._plain_text(request)}}
        return self._post_webhook(
            NotificationProvider.FEISHU,
            self.settings.feishu_webhook_url,
            payload,
            request.timeout_seconds,
        )

    def _send_wecom(self, request: NotificationTestRequest) -> NotificationResult:
        if not self.settings.wecom_webhook_url:
            return self._not_configured(NotificationProvider.WECOM, "WECOM_WEBHOOK_URL")

        payload = {
            "msgtype": "markdown",
            "markdown": {"content": f"**{request.title}**\n\n{request.message}"},
        }
        return self._post_webhook(
            NotificationProvider.WECOM,
            self.settings.wecom_webhook_url,
            payload,
            request.timeout_seconds,
        )

    def _send_telegram(self, request: NotificationTestRequest) -> NotificationResult:
        if not self.settings.telegram_bot_token or not self.settings.telegram_chat_id:
            return self._not_configured(
                NotificationProvider.TELEGRAM,
                "TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID",
            )

        url = f"https://api.telegram.org/bot{self.settings.telegram_bot_token}/sendMessage"
        payload = {"chat_id": self.settings.telegram_chat_id, "text": self._plain_text(request)}
        return self._post_webhook(
            NotificationProvider.TELEGRAM,
            url,
            payload,
            request.timeout_seconds,
        )

    def _send_email(self, request: NotificationTestRequest) -> NotificationResult:
        required = {
            "EMAIL_SMTP_HOST": self.settings.email_smtp_host,
            "EMAIL_FROM": self.settings.email_from,
            "EMAIL_TO": self.settings.email_to,
        }
        missing = [key for key, value in required.items() if not value]
        if missing:
            return self._not_configured(NotificationProvider.EMAIL, " and ".join(missing))

        message = EmailMessage()
        message["Subject"] = request.title
        message["From"] = self.settings.email_from or ""
        message["To"] = self.settings.email_to or ""
        message.set_content(request.message)

        try:
            with smtplib.SMTP(
                self.settings.email_smtp_host,
                self.settings.email_smtp_port,
                timeout=request.timeout_seconds,
            ) as smtp:
                if self.settings.email_use_tls:
                    smtp.starttls()
                if self.settings.email_smtp_username or self.settings.email_smtp_password:
                    smtp.login(
                        self.settings.email_smtp_username or "",
                        self.settings.email_smtp_password or "",
                    )
                smtp.send_message(message)
        except (OSError, smtplib.SMTPException) as exc:
            return NotificationResult(
                success=False,
                provider=NotificationProvider.EMAIL.value,
                message=str(exc),
            )

        return self._sent(NotificationProvider.EMAIL)

    def _send_slack(self, request: NotificationTestRequest) -> NotificationResult:
        if not self.settings.slack_webhook_url:
            return self._not_configured(NotificationProvider.SLACK, "SLACK_WEBHOOK_URL")

        payload = {"text": self._plain_text(request)}
        return self._post_webhook(
            NotificationProvider.SLACK,
            self.settings.slack_webhook_url,
            payload,
            request.timeout_seconds,
        )

    def _send_discord(self, request: NotificationTestRequest) -> NotificationResult:
        if not self.settings.discord_webhook_url:
            return self._not_configured(NotificationProvider.DISCORD, "DISCORD_WEBHOOK_URL")

        payload = {"content": self._plain_text(request)}
        return self._post_webhook(
            NotificationProvider.DISCORD,
            self.settings.discord_webhook_url,
            payload,
            request.timeout_seconds,
        )

    def _post_webhook(
        self,
        provider: NotificationProvider,
        url: str,
        payload: dict[str, object],
        timeout_seconds: int,
    ) -> NotificationResult:
        try:
            response = httpx.post(url, json=payload, timeout=timeout_seconds)
            response.raise_for_status()
        except httpx.RequestError as exc:
            return NotificationResult(
                success=False,
                provider=provider.value,
                message=f"request failed: {exc.__class__.__name__}",
            )
        except httpx.HTTPStatusError as exc:
            return NotificationResult(
                success=False,
                provider=provider.value,
                message=f"HTTP {exc.response.status_code}: {exc.response.reason_phrase}",
            )

        return self._sent(provider)

    @staticmethod
    def _plain_text(request: NotificationTestRequest) -> str:
        title = request.title.strip()
        message = request.message.strip()
        if not title:
            return message
        if not message:
            return title
        return f"{title}\n{message}"

    @staticmethod
    def _not_configured(provider: NotificationProvider, setting_name: str) -> NotificationResult:
        return NotificationResult(
            success=False,
            provider=provider.value,
            message=f"{setting_name} is not configured",
        )

    @staticmethod
    def _sent(provider: NotificationProvider) -> NotificationResult:
        return NotificationResult(success=True, provider=provider.value, message="notification sent")


FeishuNotificationService = NotificationService
