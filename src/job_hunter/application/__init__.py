"""Human-approved application channels and email drafting."""

from .detector import detect_application_channel, detect_language
from .email_composer import EmailComposer
from .email_sender import DummyEmailProvider, EmailProvider, GmailEmailProvider, send_approved_email
from .models import ApplicationDetection, ApplicationMethod, EmailDraft, EmailDraftStatus, JobLanguage

__all__ = ["ApplicationDetection", "ApplicationMethod", "DummyEmailProvider", "EmailComposer",
           "EmailDraft", "EmailDraftStatus", "EmailProvider", "GmailEmailProvider", "JobLanguage",
           "detect_application_channel", "detect_language", "send_approved_email"]
