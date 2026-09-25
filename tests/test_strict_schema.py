import unittest

from agentic_anex.llm_clients.strict_schema import UNSUPPORTED_KEYWORDS, to_openai_strict
from agentic_anex.orchestration import AGENT_DECISION_JSON_SCHEMA


def walk(node):
    """Every subschema in the document, including the document itself."""
    if isinstance(node, dict):
        yield node
        for key, value in node.items():
            if key == "properties":
                for sub in value.values():
                    yield from walk(sub)
            elif key in ("items", "additionalProperties", "not"):
                yield from walk(value)
            elif key in ("anyOf", "oneOf", "allOf", "prefixItems"):
                for sub in value:
                    yield from walk(sub)
    elif isinstance(node, list):
        for item in node:
            yield from walk(item)


class StrictSchemaTests(unittest.TestCase):
    def setUp(self):
        self.strict = to_openai_strict(AGENT_DECISION_JSON_SCHEMA)

    def test_the_source_schema_is_not_mutated(self):
        before = repr(AGENT_DECISION_JSON_SCHEMA)
        to_openai_strict(AGENT_DECISION_JSON_SCHEMA)
        self.assertEqual(repr(AGENT_DECISION_JSON_SCHEMA), before)

    def test_no_unsupported_keyword_survives(self):
        for node in walk(self.strict):
            leftover = sorted(UNSUPPORTED_KEYWORDS & set(node))
            self.assertEqual(leftover, [], f"{leftover} survived in {sorted(node)}")

    def test_every_object_requires_all_of_its_properties(self):
        for node in walk(self.strict):
            if isinstance(node.get("properties"), dict):
                self.assertEqual(sorted(node["required"]), sorted(node["properties"]))
                self.assertIs(node["additionalProperties"], False)

    def test_const_becomes_a_typed_single_value_enum(self):
        request = self.strict["properties"]["request"]["properties"]
        self.assertEqual(request["workload"]["enum"], ["one_shot"])
        self.assertEqual(request["workload"]["type"], "string")
        self.assertEqual(request["objective"]["enum"], ["minimize_latency"])
        for node in walk(self.strict):
            self.assertNotIn("const", node)

    def test_every_subschema_declares_a_type_or_a_composite(self):
        """The strict subset rejects a subschema with no type key."""
        for node in walk(self.strict):
            if set(node) <= {"description"}:
                continue
            self.assertTrue(
                "type" in node or "anyOf" in node or "oneOf" in node or "allOf" in node,
                f"no type on {sorted(node)}")

    def test_previously_optional_properties_become_nullable(self):
        request = self.strict["properties"]["request"]["properties"]
        # seed and latency_target_slots were optional in the source schema
        self.assertIn("null", request["seed"]["type"])
        self.assertIn("null", request["latency_target_slots"]["type"])
        # channels was required, so it stays non-nullable
        self.assertEqual(request["channels"]["type"], "integer")

    def test_required_properties_are_not_made_nullable(self):
        top = self.strict["properties"]
        self.assertEqual(top["status"]["type"], "string")
        self.assertNotIn(None, top["status"]["enum"])

    def test_clarification_question_objects_keep_their_four_fields(self):
        item = self.strict["properties"]["clarification_questions"]["items"]
        self.assertEqual(sorted(item["required"]),
                         ["expected_type", "field", "question", "reason"])
        self.assertIs(item["additionalProperties"], False)

    def test_a_schema_without_objects_is_returned_intact_apart_from_bounds(self):
        self.assertEqual(to_openai_strict({"type": "string", "maxLength": 5}),
                         {"type": "string"})

    def test_a_non_object_document_is_rejected(self):
        with self.assertRaises(TypeError):
            to_openai_strict([{"type": "string"}])


if __name__ == "__main__":
    unittest.main()
