from paperless_ai_extract.config import RecipientConfig
from paperless_ai_extract.domain.evidence import (confirmed_joint_address,
                                                   joint_address_alias, validated_recipient)

from conftest import JOINT, LETTER

RC = RecipientConfig(enabled=True, shared="Shared", shared_keywords=["familie"],
                     aliases={JOINT: ["Muster/Beispiel"], "Kim Muster": ["Kimi Muster"]})


def test_unassigned_passes_through():
    assert validated_recipient("Unassigned", "", LETTER, RC) == "Unassigned"


def test_certificate_holder_without_postal_address():
    text = "Zertifikat\nKim Muster\nhat die Ausbildung abgeschlossen.\nLeitung: Alex Muster"
    assert validated_recipient("Kim Muster", "Kim Muster", text, RC) == "Kim Muster"
    assert validated_recipient("Sam Beispiel", "Sam Beispiel", text, RC) == "Unassigned"


def test_quote_must_occur_in_document():
    assert validated_recipient("Alex Muster", "Alex Muster", LETTER, RC) == "Unassigned"


def test_person_with_title_and_middle_name():
    text = "Herrn Dr. Alex Peter Muster\nWeg 1\n12345 Ort"
    assert validated_recipient("Alex Muster", "Dr. Alex Peter Muster", text, RC) == "Alex Muster"


def test_person_alias():
    text = "Kimi Muster\nWeg 1\n12345 Ort"
    assert validated_recipient("Kim Muster", "Kimi Muster", text, RC) == "Kim Muster"


def test_joint_requires_both_names_or_postal_alias():
    assert validated_recipient(JOINT, "Muster/Beispiel", LETTER, RC) == JOINT
    only_one = "Alex Muster\nWeg 1\n12345 Ort"
    assert validated_recipient(JOINT, "Alex Muster", only_one, RC) == "Unassigned"
    both = "Alex Muster und Sam Beispiel\nWeg 1\n12345 Ort"
    assert validated_recipient(JOINT, "Alex Muster und Sam Beispiel", both, RC) == JOINT


def test_shared_needs_keyword():
    assert validated_recipient("Shared", "Familie Muster", "An Familie Muster", RC) == "Shared"
    assert validated_recipient("Shared", "Muster", "An Muster", RC) == "Unassigned"


def test_joint_alias_in_body_text_is_not_an_address():
    body = "Wie mit Muster/Beispiel besprochen, senden wir die Unterlagen."
    assert not joint_address_alias(JOINT, "Muster/Beispiel", body, RC.aliases)


def test_joint_alias_after_sender_label_is_rejected():
    text = "Absender:\nMuster/Beispiel\nHauptstrasse 12\n12345 Musterstadt"
    assert not joint_address_alias(JOINT, "Muster/Beispiel", text, RC.aliases)


def test_joint_alias_with_trailing_customer_number():
    text = "Muster/Beispiel 0815/4711\nHauptstrasse 12\n12345 Musterstadt"
    assert joint_address_alias(JOINT, "Muster/Beispiel 0815/4711", text, RC.aliases)


def test_two_readings_must_agree():
    assert confirmed_joint_address([LETTER, LETTER], RC.aliases) == JOINT
    assert confirmed_joint_address([LETTER, "noise"], RC.aliases) is None
    assert confirmed_joint_address([LETTER], RC.aliases) is None
