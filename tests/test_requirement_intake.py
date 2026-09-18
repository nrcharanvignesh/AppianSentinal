from __future__ import annotations

from pathlib import Path
from typing import Any

import httpx
import pytest

from appian_sentinel.analyzer import pdf_extractor
from appian_sentinel.integrations import ado_client
from appian_sentinel.models.user_story import AcceptanceCriterion, UserStory


class FakeStructuredLLM:
    async def chat_structured(
        self,
        messages: list[dict[str, Any]],
        *,
        response_schema: type[UserStory],
        model: str,
    ) -> UserStory:
        del response_schema, model
        document = messages[-1]["content"]
        assert "As a requester" in document
        return UserStory(
            title="Submit request",
            description="A requester submits a request.",
            as_a="requester",
            i_want="to submit a request",
            so_that="it can be approved",
            acceptance_criteria=[
                AcceptanceCriterion(
                    id="AC-1",
                    description="The request is saved.",
                    given="valid request data",
                    when="the requester submits",
                    then="the request is saved",
                )
            ],
        )


def _story_text() -> str:
    return (
        "Submit request\n"
        "As a requester, I want to submit a request, so that it can be approved.\n"
        "AC-1: Given valid request data, when the requester submits, "
        "then the request is saved."
    )


def _write_text_pdf(path: Path, text: str) -> None:
    escaped = text.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")
    content = f"BT /F1 11 Tf 72 720 Td ({escaped}) Tj ET".encode("ascii")
    objects = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        (
            b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] "
            b"/Resources << /Font << /F1 5 0 R >> >> /Contents 4 0 R >>"
        ),
        b"<< /Length " + str(len(content)).encode("ascii") + b" >>\nstream\n" + content + b"\nendstream",
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
    ]
    pdf = bytearray(b"%PDF-1.4\n")
    offsets = [0]
    for number, obj in enumerate(objects, start=1):
        offsets.append(len(pdf))
        pdf.extend(f"{number} 0 obj\n".encode("ascii"))
        pdf.extend(obj)
        pdf.extend(b"\nendobj\n")
    xref_offset = len(pdf)
    pdf.extend(f"xref\n0 {len(objects) + 1}\n".encode("ascii"))
    pdf.extend(b"0000000000 65535 f \n")
    for offset in offsets[1:]:
        pdf.extend(f"{offset:010d} 00000 n \n".encode("ascii"))
    pdf.extend(
        (
            f"trailer\n<< /Size {len(objects) + 1} /Root 1 0 R >>\n"
            f"startxref\n{xref_offset}\n%%EOF\n"
        ).encode("ascii")
    )
    path.write_bytes(pdf)


@pytest.fixture
def fake_llm(monkeypatch: pytest.MonkeyPatch) -> FakeStructuredLLM:
    fake = FakeStructuredLLM()
    monkeypatch.setattr(pdf_extractor.llm, "chat_structured", fake.chat_structured)
    return fake


async def test_chat_intake_normalizes_story_with_traceability(
    fake_llm: FakeStructuredLLM,
) -> None:
    del fake_llm
    story = await pdf_extractor.extract_user_story_from_text(
        _story_text(),
        source_id="chat-session-7",
        source_kind="chat",
    )

    assert story.as_a == "requester"
    assert story.acceptance_criteria[0].then == "the request is saved"
    assert (story.source_id, story.source_kind) == ("chat-session-7", "chat")
    assert {
        (criterion.source_id, criterion.source_kind)
        for criterion in story.acceptance_criteria
    } == {("chat-session-7", "chat")}
    assert story.raw_text == _story_text()


async def test_pdf_intake_extracts_real_pdf_and_retains_traceability(
    tmp_path: Path,
    fake_llm: FakeStructuredLLM,
) -> None:
    del fake_llm
    pdf_path = tmp_path / "REQ-16.pdf"
    _write_text_pdf(pdf_path, _story_text())

    story = await pdf_extractor.extract_user_story(pdf_path)

    assert "As a requester" in story.raw_text
    assert (story.source_id, story.source_kind) == ("REQ-16.pdf", "pdf")
    assert {
        (criterion.source_id, criterion.source_kind)
        for criterion in story.acceptance_criteria
    } == {("REQ-16.pdf", "pdf")}


async def test_ado_pat_intake_uses_rest_payload_and_retains_traceability(
    monkeypatch: pytest.MonkeyPatch,
    fake_llm: FakeStructuredLLM,
) -> None:
    del fake_llm

    def respond(request: httpx.Request) -> httpx.Response:
        assert request.headers["Authorization"].startswith("Basic ")
        assert request.url.params["api-version"] == "7.1"
        return httpx.Response(
            200,
            json={
                "id": 42,
                "url": str(request.url),
                "fields": {
                    "System.Title": "Submit request",
                    "System.Description": (
                        "<p>As a requester, I want to submit a request, "
                        "so that it can be approved.</p>"
                    ),
                    "Microsoft.VSTS.Common.AcceptanceCriteria": (
                        "<p>AC-1: Given valid request data, when the requester "
                        "submits, then the request is saved.</p>"
                    ),
                    "System.WorkItemType": "User Story",
                    "System.State": "Active",
                },
            },
        )

    real_async_client = httpx.AsyncClient
    transport = httpx.MockTransport(respond)

    def client_factory(*args: Any, **kwargs: Any) -> httpx.AsyncClient:
        kwargs["transport"] = transport
        return real_async_client(*args, **kwargs)

    monkeypatch.setattr(ado_client.httpx, "AsyncClient", client_factory)
    work_item = await ado_client.get_work_item("contoso", "Sentinel", 42, "test-pat")
    story = await pdf_extractor.extract_user_story_from_text(
        work_item["combined_text"],
        source_id=str(work_item["id"]),
        source_kind="ado",
    )

    assert work_item["acceptance_criteria"].startswith("AC-1:")
    assert (story.source_id, story.source_kind) == ("42", "ado")
    assert {
        (criterion.source_id, criterion.source_kind)
        for criterion in story.acceptance_criteria
    } == {("42", "ado")}


async def test_ado_mcp_payload_normalizes_through_configured_bridge_contract(
    fake_llm: FakeStructuredLLM,
) -> None:
    del fake_llm
    story = await pdf_extractor.extract_user_story_from_text(
        _story_text(),
        source_id="ado-mcp:42",
        source_kind="ado",
    )

    assert story.acceptance_criteria[0].description == "The request is saved."
    assert (story.source_id, story.source_kind) == ("ado-mcp:42", "ado")
    assert {
        criterion.source_id for criterion in story.acceptance_criteria
    } == {"ado-mcp:42"}
