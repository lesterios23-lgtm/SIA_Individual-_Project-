"""Tests for the documented gateway HTTP contract."""

from __future__ import annotations

import json
import uuid

import requests
from django.test import SimpleTestCase

from limbus_integration.client import GatewayClient


class FakeResponse:
    def __init__(self, status_code=202, body=None, headers=None, text=None):
        self.status_code = status_code
        self._body = body
        self.headers = headers or {}
        if text is not None:
            self.text = text
        elif body is not None:
            self.text = json.dumps(body)
        else:
            self.text = ""

    def json(self):
        if self._body is not None:
            return self._body
        if self.text:
            return json.loads(self.text)
        raise ValueError("No JSON object could be decoded")


class FakeSession:
    def __init__(self, post_responses=None, get_responses=None):
        self.post_responses = list(post_responses or [])
        self.get_responses = list(get_responses or [])
        self.posts = []
        self.gets = []

    def post(self, url, **kwargs):
        self.posts.append((url, kwargs))
        response = self.post_responses.pop(0)
        if isinstance(response, Exception):
            raise response
        return response

    def get(self, url, **kwargs):
        self.gets.append((url, kwargs))
        response = self.get_responses.pop(0)
        if isinstance(response, Exception):
            raise response
        return response


class GatewayClientTests(SimpleTestCase):
    def setUp(self):
        self.event_id = str(uuid.uuid4())
        self.envelope = {
            "event_id": self.event_id,
            "source_system": "hr",
            "event_type": "hr.employee.upsert",
            "occurred_at": "2026-11-20T10:30:00Z",
            "correlation_id": "hr-employee-EMP-001",
            "external_id": "EMP-001",
            "payload": {"employee_id": "EMP-001", "status": "active"},
        }

    def _client(self, session):
        return GatewayClient(
            base_url="http://gateway.test/api/v1/integration",
            token="test-token",
            timeout=5,
            session=session,
        )

    def test_post_uses_documented_url_headers_and_body(self):
        session = FakeSession(
            [FakeResponse(202, {"event_id": self.event_id, "status": "received"})]
        )
        response = self._client(session).post_event(self.envelope)

        self.assertEqual(response.http_status, 202)
        self.assertEqual(response.gateway_status, "received")
        self.assertFalse(response.retryable)

        url, kwargs = session.posts[0]
        self.assertEqual(url, "http://gateway.test/api/v1/integration/events/")
        self.assertEqual(kwargs["json"], self.envelope)
        self.assertEqual(kwargs["headers"]["Authorization"], "Bearer test-token")
        self.assertEqual(kwargs["headers"]["Content-Type"], "application/json")
        self.assertEqual(kwargs["headers"]["Idempotency-Key"], self.event_id)
        self.assertEqual(kwargs["headers"]["X-Limbus-System"], "hr")
        self.assertEqual(kwargs["timeout"], 5)

    def test_duplicate_is_not_retryable(self):
        session = FakeSession(
            [FakeResponse(202, {"event_id": self.event_id, "status": "duplicate"})]
        )
        response = self._client(session).post_event(self.envelope)
        self.assertEqual(response.gateway_status, "duplicate")
        self.assertFalse(response.retryable)

    def test_400_is_not_retryable_and_carries_field_errors(self):
        session = FakeSession(
            [
                FakeResponse(
                    400,
                    {
                        "code": "invalid_payload",
                        "message": "payload is invalid",
                        "fields": {"payload.status": "is required"},
                    },
                )
            ]
        )
        response = self._client(session).post_event(self.envelope)
        self.assertFalse(response.retryable)
        self.assertEqual(response.error_code, "invalid_payload")
        self.assertEqual(response.error_fields, {"payload.status": "is required"})

    def test_401_and_403_are_not_retryable(self):
        for status in (401, 403):
            session = FakeSession(
                [FakeResponse(status, {"code": "denied", "message": "no"})]
            )
            response = self._client(session).post_event(self.envelope)
            self.assertFalse(response.retryable, status)
            self.assertEqual(response.http_status, status)

    def test_409_conflict_is_not_retryable(self):
        session = FakeSession(
            [FakeResponse(409, {"code": "conflict", "message": "different payload"})]
        )
        response = self._client(session).post_event(self.envelope)
        self.assertFalse(response.retryable)

    def test_500_is_retryable(self):
        session = FakeSession(
            [FakeResponse(503, {"code": "unavailable", "message": "try later"})]
        )
        response = self._client(session).post_event(self.envelope)
        self.assertTrue(response.retryable)

    def test_429_honours_retry_after(self):
        session = FakeSession(
            [
                FakeResponse(
                    429,
                    {"code": "rate_limited", "message": "slow down"},
                    headers={"Retry-After": "12"},
                )
            ]
        )
        response = self._client(session).post_event(self.envelope)
        self.assertTrue(response.retryable)
        self.assertEqual(response.retry_after, 12.0)

    def test_timeout_is_retryable_and_never_leaks_the_token(self):
        session = FakeSession([requests.Timeout("timed out")])
        response = self._client(session).post_event(self.envelope)
        self.assertTrue(response.retryable)
        self.assertEqual(response.http_status, None)
        self.assertNotIn("test-token", response.error_message or "")

    def test_event_id_mismatch_is_not_retryable(self):
        session = FakeSession(
            [
                FakeResponse(
                    202,
                    {"event_id": str(uuid.uuid4()), "status": "received"},
                )
            ]
        )
        response = self._client(session).post_event(self.envelope)
        self.assertFalse(response.retryable)
        self.assertEqual(response.error_code, "event_id_mismatch")

    def test_get_event_uses_documented_path(self):
        session = FakeSession(
            get_responses=[
                FakeResponse(
                    200,
                    {
                        "event_id": self.event_id,
                        "status": "succeeded",
                        "attempt_count": 1,
                    },
                )
            ]
        )
        response = self._client(session).get_event(self.event_id)
        self.assertEqual(response.gateway_status, "succeeded")
        url, kwargs = session.gets[0]
        self.assertEqual(
            url,
            "http://gateway.test/api/v1/integration/events/%s/" % self.event_id,
        )
        self.assertEqual(kwargs["headers"]["X-Limbus-System"], "hr")
        self.assertNotIn("Idempotency-Key", kwargs["headers"])
