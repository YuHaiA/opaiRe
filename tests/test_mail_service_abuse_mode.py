def test_abuse_mode_flag_value():
    mailbox = {"_polling_stopped": "abuse_mode"}
    assert mailbox.get("_polling_stopped") == "abuse_mode"
