import unittest

from src.pipeline.contracts import MessageEnvelope, Participant
from src.pipeline.identity_resolution import ParticipantRegistry, registry_from_mailex_record, resolve_assignee, resolve_name

REG = ParticipantRegistry([
    Participant("riya", "Riya Sharma", ["Riya"]),
    Participant("bianca", "Bianca Sawant", ["Bianca"], ["bianca@example.com"]),
    Participant("anna_l", "Anna Lee", ["Anna"]),
    Participant("anna_r", "Anna Roy", ["Anna"]),
    Participant("dev", "Dev Patel", []),
])


def env(text, sender="bianca", recipients=("riya",)):
    return MessageEnvelope(message_id="m1", text=text, sender_id=sender, recipient_ids=list(recipients))


def task(text, span):
    s = text.index(span)
    return {"id": "t", "type": "TASK", "start": s, "end": s + len(span), "text": span}


def person(text, span, pid="p"):
    s = text.index(span)
    return {"id": pid, "type": "PERSON", "start": s, "end": s + len(span), "text": span}


class NameResolutionTests(unittest.TestCase):
    def test_exact_alias_and_email(self):
        self.assertEqual(resolve_name("Riya", REG).participant_id, "riya")
        self.assertEqual(resolve_name("bianca@example.com", REG).participant_id, "bianca")

    def test_unique_name_token(self):
        r = resolve_name("Sharma", REG)
        self.assertEqual((r.status, r.participant_id, r.basis), ("RESOLVED", "riya", "unique_name_token"))

    def test_title_stripped(self):
        self.assertEqual(resolve_name("Dr. Patel", REG).participant_id, "dev")

    def test_ambiguous_first_name_is_not_guessed(self):
        r = resolve_name("Anna", REG)
        self.assertEqual(r.status, "AMBIGUOUS")
        self.assertIsNone(r.participant_id)
        self.assertEqual(sorted(r.candidates), ["anna_l", "anna_r"])

    def test_unknown_and_group(self):
        self.assertEqual(resolve_name("Zed", REG).status, "UNKNOWN_PERSON")
        self.assertEqual(resolve_name("all", REG).status, "UNSUPPORTED_GROUP")
        self.assertEqual(resolve_name("Enron", REG).status, "UNSUPPORTED_GROUP")


class AssigneeTests(unittest.TestCase):
    def test_named_span(self):
        t = "Riya, please submit the report."
        r = resolve_assignee([person(t, "Riya")], task(t, "submit the report"), env(t), REG)
        self.assertEqual((r.status, r.participant_id), ("RESOLVED", "riya"))

    def test_first_person_commitment_resolves_to_sender(self):
        t = "I'll send the report by Friday."
        r = resolve_assignee([], task(t, "send the report"), env(t), REG)
        self.assertEqual((r.status, r.participant_id), ("RESOLVED_SENDER", "bianca"))

    def test_first_person_without_commitment_cue_is_unassigned(self):
        t = "I think the report is late."
        r = resolve_assignee([], task(t, "the report is late"), env(t), REG)
        self.assertEqual(r.status, "UNASSIGNED")

    def test_first_person_unknown_sender(self):
        t = "I will send the report."
        r = resolve_assignee([], task(t, "send the report"), env(t, sender="ghost"), REG)
        self.assertEqual((r.status, r.basis), ("UNASSIGNED", "first_person_unknown_sender"))

    def test_plural_we_is_not_assigned(self):
        t = "We will send the report."
        r = resolve_assignee([], task(t, "send the report"), env(t), REG)
        self.assertEqual((r.status, r.basis), ("UNASSIGNED", "first_person_plural"))

    def test_imperative_single_recipient(self):
        t = "Please send the report."
        r = resolve_assignee([], task(t, "send the report"), env(t, recipients=("riya",)), REG)
        self.assertEqual((r.status, r.participant_id), ("RESOLVED_RECIPIENT", "riya"))

    def test_imperative_sender_in_recipients_still_single_addressee(self):
        t = "Please send the report."
        r = resolve_assignee([], task(t, "send the report"), env(t, recipients=("bianca", "riya")), REG)
        self.assertEqual(r.participant_id, "riya")

    def test_imperative_multiple_recipients_is_unassigned_with_candidates(self):
        t = "Please send the report."
        r = resolve_assignee([], task(t, "send the report"), env(t, recipients=("riya", "dev")), REG)
        self.assertEqual((r.status, r.basis), ("UNASSIGNED", "multiple_recipients"))
        self.assertEqual(sorted(r.candidates), ["dev", "riya"])

    def test_imperative_no_recipients(self):
        t = "Please send the report."
        r = resolve_assignee([], task(t, "send the report"), env(t, recipients=()), REG)
        self.assertEqual((r.status, r.basis), ("UNASSIGNED", "no_recipient"))

    def test_no_evidence_is_unassigned(self):
        t = "The report was filed yesterday."
        r = resolve_assignee([], task(t, "filed"), env(t), REG)
        self.assertEqual((r.status, r.basis), ("UNASSIGNED", "no_assignee_evidence"))

    def test_multiple_distinct_assignees_have_no_owner(self):
        t = "Riya and Dev should send the report."
        r = resolve_assignee([person(t, "Riya", "p1"), person(t, "Dev", "p2")], task(t, "send the report"), env(t), REG)
        self.assertEqual((r.status, r.basis, r.participant_id), ("AMBIGUOUS", "multiple_assignees", None))
        self.assertEqual(sorted(r.candidates), ["dev", "riya"])

    def test_pronoun_spans(self):
        t = "I will send it."
        r = resolve_assignee([person(t, "I")], task(t, "send it"), env(t), REG)
        self.assertEqual(r.participant_id, "bianca")
        t2 = "You send it."
        r2 = resolve_assignee([person(t2, "You")], task(t2, "send it"), env(t2, recipients=("riya",)), REG)
        self.assertEqual(r2.participant_id, "riya")


class MailexRegistryTests(unittest.TestCase):
    def test_low_trust_parse(self):
        reg, sender, recips = registry_from_mailex_record({"sender": "Donoho, Lindy", "recipients": ["Howard", "Kevin A."]})
        self.assertEqual(reg.by_id[sender].display_name, "Lindy Donoho")
        self.assertEqual(len(recips), 1)
        self.assertEqual(reg.by_id[recips[0]].display_name, "Kevin A. Howard")
        self.assertTrue(all(p.low_trust for p in reg.participants))

    def test_email_style_recipients(self):
        reg, _, recips = registry_from_mailex_record({"sender": "K. Bass [mailto:daphneco64@alltel.net]",
                                                      "recipients": ["sherry.forbish@enron.com", "john.buchanan@enron.com"]})
        self.assertEqual(len(recips), 2)
        self.assertEqual(reg.by_id[recips[0]].display_name, "Sherry Forbish")


if __name__ == "__main__":
    unittest.main()


class NamedAddresseeTests(unittest.TestCase):
    """A request to the whole team that names one person (but the extractor linked no PERSON) goes to that person."""
    ALL = ("bianca", "dev", "anna_l")

    def resolve(self, text, span, sender="riya"):
        return resolve_assignee([], task(text, span), env(text, sender=sender, recipients=self.ALL), REG)

    def test_name_without_comma_before_the_request(self):
        r = self.resolve("Bianca please train the model.", "please train the model")
        self.assertEqual((r.status, r.participant_id, r.basis), ("RESOLVED", "bianca", "named_addressee"))

    def test_trailing_vocative(self):
        r = self.resolve("Please train the model, Dev.", "train the model")
        self.assertEqual((r.participant_id, r.basis), ("dev", "named_addressee"))

    def test_two_names_are_not_guessed(self):
        r = self.resolve("Bianca and Dev please train the model.", "please train the model")
        self.assertEqual((r.status, r.basis), ("UNASSIGNED", "multiple_recipients"))

    def test_shared_first_name_is_not_guessed(self):
        r = self.resolve("Anna please train the model.", "please train the model")
        self.assertIsNone(r.participant_id)

    def test_no_name_to_everyone_stays_unassigned(self):
        r = self.resolve("Please train the model.", "train the model")
        self.assertEqual((r.status, r.basis, sorted(r.candidates)), ("UNASSIGNED", "multiple_recipients", ["anna_l", "bianca", "dev"]))

    def test_the_senders_own_name_is_not_an_addressee(self):
        r = self.resolve("Riya please train the model.", "please train the model")
        self.assertIsNone(r.participant_id)
