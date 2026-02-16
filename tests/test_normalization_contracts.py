from src.domain.normalization import (
    normalize_campaign_status,
    normalize_lead_status,
    normalize_message_direction,
)


def test_campaign_status_normalization_contract():
    assert normalize_campaign_status("draft") == "DRAFTED"
    assert normalize_campaign_status("launching") == "DRAFTED"
    assert normalize_campaign_status("running") == "ACTIVE"
    assert normalize_campaign_status("pause") == "PAUSED"
    assert normalize_campaign_status("archived") == "STOPPED"
    assert normalize_campaign_status("pending deletion") == "STOPPED"
    assert normalize_campaign_status("done") == "COMPLETED"
    assert normalize_campaign_status("unexpected-status") == "DRAFTED"


def test_lead_status_normalization_contract():
    assert normalize_lead_status("verified") == "active"
    assert normalize_lead_status("in_sequence") == "active"
    assert normalize_lead_status("sequence_finished") == "contacted"
    assert normalize_lead_status("sequence_stopped") == "paused"
    assert normalize_lead_status("never_contacted") == "pending"
    assert normalize_lead_status("not interested") == "not_interested"
    assert normalize_lead_status("unknown") == "pending"
    assert normalize_lead_status("completely_new_value") == "unknown"


def test_message_direction_normalization_contract():
    assert normalize_message_direction("reply") == "inbound"
    assert normalize_message_direction("replied") == "inbound"
    assert normalize_message_direction("sent") == "outbound"
    assert normalize_message_direction("other") == "unknown"
