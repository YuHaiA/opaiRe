from utils.email_providers.local_microsoft_service import MailboxAbuseModeError


def test_mailbox_abuse_mode_error_contains_email():
    email = "demo@example.com"
    err = MailboxAbuseModeError(email)
    assert email in str(err)
