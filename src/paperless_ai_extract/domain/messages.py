"""User-facing note texts (English/German)."""
from __future__ import annotations

MESSAGES = {
    "en": {
        "labels": {"title": "Title", "correspondent": "Correspondent",
                   "document_type": "Document type", "storage_path": "Storage path",
                   "created": "Date", "recipient": "Recipient", "authors": "Authors",
                   "tags": "Tags"},
        "header": "AI extraction ({model}, {mode})",
        "first_run": "first analysis", "rerun": "re-analysis",
        "proposals": 'Proposed changes - add the tag "{apply}" to accept all, or edit manually:',
        "filled": "Filled automatically: {items}",
        "note": "Note: {text}",
        "empty": "(empty)", "new": "{name} (new)", "added": "+ {names}",
        "applied": "Applied AI proposal: {items}", "nothing": "nothing",
        "skipped": "Skipped (field edited since the proposal): {items}",
        "no_proposal": "AI: no stored proposal to apply; tag removed.",
        "gave_up": 'AI extraction gave up after {attempts} attempt(s): {error}\nAdd "{pending}" again to retry.',
        "reason_new_name": "new name not found in document text",
        "reason_creation_disabled": "no existing match; creation disabled",
        "reason_publication": "publication not found in document text",
        "reason_addressee": 'addressee evidence not confirmed (quote: "{quote}")',
        "reason_authors": "authors not found in document text",
        "reason_year": "year not found in document text",
        "reason_date": "date not found in document text",
        "info_storage_path": "Configured storage path {name!r} does not exist.",
        "info_recipient_window": "Recipient {name!r} confirmed by address-window OCR.",
        "info_recipient_unknown": "Recipient could not be determined.",
        "info_authors_missing": "Authors not found in document text: {names}",
    },
    "de": {
        "labels": {"title": "Titel", "correspondent": "Korrespondent",
                   "document_type": "Dokumenttyp", "storage_path": "Speicherpfad",
                   "created": "Datum", "recipient": "Empfänger", "authors": "Autoren",
                   "tags": "Tags"},
        "header": "KI-Extraktion ({model}, {mode})",
        "first_run": "Erstanalyse", "rerun": "erneute Analyse",
        "proposals": 'Vorgeschlagene Änderungen - Tag "{apply}" hinzufügen, um alle zu übernehmen, oder manuell bearbeiten:',
        "filled": "Automatisch ausgefüllt: {items}",
        "note": "Hinweis: {text}",
        "empty": "(leer)", "new": "{name} (neu)", "added": "+ {names}",
        "applied": "KI-Vorschlag übernommen: {items}", "nothing": "nichts",
        "skipped": "Übersprungen (Feld seit dem Vorschlag geändert): {items}",
        "no_proposal": "KI: kein gespeicherter Vorschlag vorhanden; Tag entfernt.",
        "gave_up": 'KI-Extraktion nach {attempts} Versuch(en) abgebrochen: {error}\nZum Wiederholen "{pending}" erneut hinzufügen.',
        "reason_new_name": "neuer Name nicht im Dokumenttext gefunden",
        "reason_creation_disabled": "kein vorhandener Eintrag; Anlegen deaktiviert",
        "reason_publication": "Publikation nicht im Dokumenttext gefunden",
        "reason_addressee": 'Empfänger nicht belegt (Zitat: "{quote}")',
        "reason_authors": "Autoren nicht im Dokumenttext gefunden",
        "reason_year": "Jahr nicht im Dokumenttext gefunden",
        "reason_date": "Datum nicht im Dokumenttext gefunden",
        "info_storage_path": "Konfigurierter Speicherpfad {name!r} existiert nicht.",
        "info_recipient_window": "Empfänger {name!r} durch Adressfenster-OCR bestätigt.",
        "info_recipient_unknown": "Empfänger konnte nicht bestimmt werden.",
        "info_authors_missing": "Autoren nicht im Dokumenttext gefunden: {names}",
    },
}


class Messages:
    def __init__(self, language: str = "en"):
        self.table = MESSAGES.get(language, MESSAGES["en"])
        self.labels = self.table["labels"]

    def __call__(self, key: str, **values) -> str:
        return self.table[key].format(**values)
