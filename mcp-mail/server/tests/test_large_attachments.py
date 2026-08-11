"""Tests for large-attachment support in the M365 (Graph) adapter.

Graph carries a message in ONE request body, which it caps at ~4MB, and the
attachment bytes ride there base64-encoded (4/3 of the raw size). Anything that
does not fit has to reach the mailbox a different way: open an upload session on
a message that ALREADY EXISTS (a draft) and PUT byte ranges to the
pre-authenticated URL Graph hands back. Every test here is offline: the HTTP
client and both token functions are stubbed, so no network, no Keychain, and
above all no mail is ever sent.

Pinned invariants:

1. Routing   -- size alone picks the route, and the two routes meet exactly at
   INLINE_ATTACHMENT_LIMIT: at or below it a file rides inline (byte-for-byte as
   before, cid: inline marking included), above it it takes createUploadSession.
   A file under that line is NEVER handed to a session, which Graph refuses with
   ErrorAttachmentSizeShouldNotBeLessThanMinimumSize; a set of small files that
   together overflow the request is refused locally, by name.
2. Chunking  -- chunks are UPLOAD_CHUNK_SIZE, which stays under Microsoft's
   documented 4MB per-PUT ceiling for this endpoint, and the Content-Range
   arithmetic is exact for both an exact multiple of the chunk size and a ragged
   final chunk.
3. Completeness -- the service answers 200 + nextExpectedRanges while the
   attachment is unfinished and 201 Created only on the range that completes it.
   The next offset comes from nextExpectedRanges, not from a local counter, and
   an upload that never sees a 201 is reported as incomplete, never as success.
4. Auth      -- the uploadUrl is pre-authenticated: the PUT carries NO
   Authorization header, and its absolute URL bypasses the client's base_url.
5. Send      -- /sendMail has no upload route, so a send with a big attachment
   becomes create draft -> upload -> POST /send. The delegated-mailbox guard
   still fires first, before any HTTP call.
6. Delegate  -- a delegated mailbox cannot take an upload session at all (Graph
   403s), so the draft paths refuse before any message is created.
7. Errors    -- a remaining hard failure names the file, its size and the real
   limit; a half-uploaded draft is named as INCOMPLETE; and a send whose outcome
   is genuinely unknown is reported as unknown, never as "NOT sent".
"""

from __future__ import annotations

import base64
from pathlib import Path
from typing import Any

import httpx
import pytest

import mcp_mail.adapters.graph as graph_mod
from mcp_mail.adapters.graph import GRAPH_BASE, GraphAdapter

UPLOAD_URL = "https://attachments.office.net/upload/session?token=abc123"


# ---- stubs ------------------------------------------------------------------


class _FakeResponse:
    def __init__(
        self,
        json_data: dict[str, Any] | None = None,
        status_code: int = 200,
        text: str = "",
    ) -> None:
        self._json = json_data or {}
        self.status_code = status_code
        self.text = text

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise httpx.HTTPStatusError(
                f"HTTP {self.status_code}", request=None, response=None  # type: ignore[arg-type]
            )

    def json(self) -> dict[str, Any]:
        return self._json


class _UploadClient:
    """Records every verb. Answers createReply/createDraft/createUploadSession,
    and completes a chunked PUT the way Microsoft documents this session: 200 OK
    carrying nextExpectedRanges while the attachment is unfinished, 201 Created
    on the byte range that completes it. 202 is never returned."""

    def __init__(
        self,
        put_status: int | None = None,
        put_text: str = "",
        session_status: int = 200,
        session_text: str = "",
        put_hook: Any = None,
        session_fail_on: str | None = None,
        send_raises: Exception | None = None,
        send_status: int | None = None,
    ) -> None:
        self.posts: list[dict[str, Any]] = []
        self.patches: list[dict[str, Any]] = []
        self.gets: list[dict[str, Any]] = []
        self.puts: list[dict[str, Any]] = []
        self.deletes: list[dict[str, Any]] = []
        # Forces every chunk PUT to this status when set (failure simulation).
        self._put_status = put_status
        self._put_text = put_text
        self._session_status = session_status
        self._session_text = session_text
        # put_hook(index, start, end, total) -> _FakeResponse | None; None keeps
        # the documented default answer. Lets a test model a service that commits
        # fewer bytes than it was handed.
        self._put_hook = put_hook
        # Name of the attachment whose createUploadSession is refused.
        self._session_fail_on = session_fail_on
        # How POST .../send behaves: raise (transport failure) or a status.
        self._send_raises = send_raises
        self._send_status = send_status

    def get(self, url: str, **kwargs: Any) -> _FakeResponse:
        self.gets.append({"url": url})
        return _FakeResponse(
            {
                "id": "m1",
                "from": {"emailAddress": {"address": "sender@example.org"}},
                "toRecipients": [],
                "ccRecipients": [],
                "hasAttachments": False,
                "body": {"contentType": "html", "content": "orig"},
            }
        )

    def post(self, url: str, **kwargs: Any) -> _FakeResponse:
        self.posts.append(
            {"url": url, "json": kwargs.get("json"), "headers": kwargs.get("headers")}
        )
        if url.endswith("/createUploadSession"):
            name = ((kwargs.get("json") or {}).get("AttachmentItem") or {}).get("name")
            if self._session_fail_on and name == self._session_fail_on:
                return _FakeResponse(
                    {}, status_code=503, text='{"error":{"code":"ServiceUnavailable"}}'
                )
            return _FakeResponse(
                {"uploadUrl": UPLOAD_URL},
                status_code=self._session_status,
                text=self._session_text,
            )
        if url.endswith("/createReply"):
            return _FakeResponse({"id": "draft-99", "webLink": "https://outlook/draft-99"})
        if url.endswith("/send"):
            if self._send_raises is not None:
                raise self._send_raises
            return _FakeResponse({}, status_code=self._send_status or 202)
        return _FakeResponse(
            {"id": "draft-1", "webLink": "https://outlook/draft-1", "isDraft": True}
        )

    def patch(self, url: str, **kwargs: Any) -> _FakeResponse:
        self.patches.append({"url": url, "json": kwargs.get("json")})
        return _FakeResponse({"id": "draft-99"})

    def put(self, url: str, **kwargs: Any) -> _FakeResponse:
        headers = kwargs.get("headers") or {}
        content = kwargs.get("content") or b""
        self.puts.append(
            {
                "url": url,
                "headers": headers,
                "content": content,
                "range": headers.get("Content-Range"),
                "timeout": kwargs.get("timeout"),
            }
        )
        if self._put_status is not None:
            return _FakeResponse({}, status_code=self._put_status, text=self._put_text)
        rng = headers.get("Content-Range", "")
        span, _, total_s = rng.partition("/")
        start = int(span.split(" ")[-1].split("-")[0])
        end = int(span.split("-")[-1])
        total = int(total_s)
        if self._put_hook is not None:
            forced = self._put_hook(len(self.puts) - 1, start, end, total)
            if forced is not None:
                return forced
        # Documented contract: 201 Created is the ONLY completion signal; every
        # earlier range answers 200 OK saying where to resume from.
        if end + 1 >= total:
            return _FakeResponse({}, status_code=201)
        return _FakeResponse({"nextExpectedRanges": [f"{end + 1}"]}, status_code=200)

    def delete(self, url: str, **kwargs: Any) -> _FakeResponse:
        self.deletes.append({"url": url})
        return _FakeResponse({})


class _Acct:
    id = "acct"
    auto_write = True
    signature = None

    def __init__(self, mailbox: str | None = None, address: str = "me@example.com") -> None:
        self.mailbox = mailbox
        self.address = address


@pytest.fixture
def make_graph(monkeypatch: pytest.MonkeyPatch):
    """GraphAdapter whose _headers runs FOR REAL against stubbed token functions,
    so tests can tell an authenticated Graph call from an unauthenticated PUT."""

    monkeypatch.setattr(graph_mod, "acquire_token", lambda acct: "mail-token")
    monkeypatch.setattr(graph_mod, "acquire_shared_token", lambda acct: "shared-token")

    def _make(
        mailbox: str | None = None, **client_kwargs: Any
    ) -> tuple[GraphAdapter, _UploadClient]:
        adapter = GraphAdapter(_Acct(mailbox=mailbox))  # type: ignore[arg-type]
        client = _UploadClient(**client_kwargs)
        adapter._client = client  # type: ignore[assignment]
        return adapter, client

    return _make


@pytest.fixture
def tiny_limits(monkeypatch: pytest.MonkeyPatch) -> None:
    """Shrink the thresholds so the arithmetic can be exercised on byte-scale
    files. The production values are pinned separately, in their own test."""
    monkeypatch.setattr(graph_mod, "INLINE_ATTACHMENT_LIMIT", 1024)
    monkeypatch.setattr(graph_mod, "INLINE_TOTAL_LIMIT", 4096)
    monkeypatch.setattr(graph_mod, "UPLOAD_CHUNK_SIZE", 4096)


def _write(tmp_path: Path, name: str, size: int) -> str:
    p = tmp_path / name
    p.write_bytes((b"0123456789abcdef" * (size // 16 + 1))[:size])
    return str(p)


def _ranges(client: _UploadClient) -> list[str]:
    return [p["range"] for p in client.puts]


# ---- constants ---------------------------------------------------------------


def test_chunk_size_stays_under_the_documented_4mb_per_put_ceiling() -> None:
    # The only per-PUT limit Microsoft documents for the OUTLOOK attachment
    # session is 4MB ("keep each byte range less than 4 MB", repeated on the
    # Content-Length header). The 320 KiB-multiple rule belongs to the OneDrive
    # driveItem session and does NOT govern this endpoint, so it may not be used
    # to justify a chunk above the ceiling.
    assert graph_mod.UPLOAD_CHUNK_SIZE <= 4 * 1000 * 1000
    assert graph_mod.UPLOAD_CHUNK_SIZE <= 4 * 1024 * 1024
    assert graph_mod.UPLOAD_CHUNK_SIZE > 0


def test_request_budget_admits_one_file_at_the_per_file_limit() -> None:
    # The per-file threshold and the request-wide budget must not contradict each
    # other: if the budget were smaller than the encoded cost of a single file at
    # INLINE_ATTACHMENT_LIMIT, that file would be too big to ride inline and too
    # small for an upload session, i.e. unsendable by either route.
    assert graph_mod.INLINE_TOTAL_LIMIT >= GraphAdapter._b64_size(
        graph_mod.INLINE_ATTACHMENT_LIMIT
    )


def test_b64_size_matches_real_base64_length() -> None:
    for raw in (0, 1, 2, 3, 4, 100, 999, 1024, 3 * 1024 * 1024 - 1):
        assert GraphAdapter._b64_size(raw) == len(base64.b64encode(b"x" * raw))
    # ...and it is the ceil(raw * 4 / 3) wire cost the budget is measured in.
    assert GraphAdapter._b64_size(3 * 1024 * 1024) == 4 * 1024 * 1024


# ---- the small path is untouched --------------------------------------------


def test_small_attachment_still_rides_inline_in_one_request(
    make_graph, tmp_path: Path
) -> None:
    adapter, client = make_graph()
    att = _write(tmp_path, "note.txt", 16)

    adapter.create_draft(
        to=["dest@example.org"], subject="Hi", body_html="<p>hi</p>", attachments=[att]
    )

    # One POST, no upload session, no PUT: exactly the pre-existing behaviour.
    assert [p["url"] for p in client.posts] == ["/me/messages"]
    assert client.puts == []
    payload = client.posts[0]["json"]["attachments"][0]
    assert payload["@odata.type"] == "#microsoft.graph.fileAttachment"
    assert payload["name"] == "note.txt"
    assert base64.b64decode(payload["contentBytes"]) == Path(att).read_bytes()
    assert "isInline" not in payload


def test_small_cid_attachment_is_still_marked_inline(make_graph, tmp_path: Path) -> None:
    adapter, client = make_graph()
    logo = _write(tmp_path, "logo.png", 64)

    adapter.create_draft(
        to=["dest@example.org"],
        subject="Hi",
        body_html='<p>hi</p><img src="cid:logo.png">',
        attachments=[logo],
    )

    payload = client.posts[0]["json"]["attachments"][0]
    assert payload["isInline"] is True
    assert payload["contentId"] == "logo.png"
    assert client.puts == []


def test_send_without_large_attachments_still_uses_sendmail(
    make_graph, tmp_path: Path
) -> None:
    adapter, client = make_graph()
    att = _write(tmp_path, "note.txt", 16)

    adapter.send(
        to=["dest@example.org"], subject="Hi", body_text="hi", attachments=[att]
    )

    assert [p["url"] for p in client.posts] == ["/me/sendMail"]
    assert client.posts[0]["json"]["saveToSentItems"] is True
    assert client.puts == []


# ---- chunk arithmetic --------------------------------------------------------


def test_upload_chunks_exact_multiple_of_chunk_size(
    make_graph, tiny_limits, tmp_path: Path
) -> None:
    adapter, client = make_graph()
    att = _write(tmp_path, "big.bin", 12288)  # exactly 3 chunks of 4096

    adapter.create_draft(
        to=["dest@example.org"], subject="Hi", body_text="hi", attachments=[att]
    )

    # A file that ends exactly on a chunk boundary must not emit a fourth,
    # empty range: the loop stops the moment start reaches total.
    assert _ranges(client) == [
        "bytes 0-4095/12288",
        "bytes 4096-8191/12288",
        "bytes 8192-12287/12288",
    ]
    assert all(len(p["content"]) == 4096 for p in client.puts)
    assert b"".join(p["content"] for p in client.puts) == Path(att).read_bytes()


def test_upload_chunks_ragged_final_chunk(make_graph, tiny_limits, tmp_path: Path) -> None:
    adapter, client = make_graph()
    att = _write(tmp_path, "big.bin", 10000)  # 4096 + 4096 + 1808

    adapter.create_draft(
        to=["dest@example.org"], subject="Hi", body_text="hi", attachments=[att]
    )

    assert _ranges(client) == [
        "bytes 0-4095/10000",
        "bytes 4096-8191/10000",
        "bytes 8192-9999/10000",
    ]
    assert [len(p["content"]) for p in client.puts] == [4096, 4096, 1808]
    assert b"".join(p["content"] for p in client.puts) == Path(att).read_bytes()


def test_single_chunk_file_smaller_than_chunk_size(
    make_graph, tiny_limits, tmp_path: Path
) -> None:
    adapter, client = make_graph()
    att = _write(tmp_path, "big.bin", 2500)  # over the inline limit, under a chunk

    adapter.create_draft(
        to=["dest@example.org"], subject="Hi", body_text="hi", attachments=[att]
    )

    assert _ranges(client) == ["bytes 0-2499/2500"]
    assert len(client.puts) == 1


def test_upload_session_declares_the_real_file_size(
    make_graph, tiny_limits, tmp_path: Path
) -> None:
    adapter, client = make_graph()
    att = _write(tmp_path, "big.bin", 2500)

    adapter.create_draft(
        to=["dest@example.org"], subject="Hi", body_text="hi", attachments=[att]
    )

    session = next(p for p in client.posts if p["url"].endswith("/createUploadSession"))
    assert session["url"] == "/me/messages/draft-1/attachments/createUploadSession"
    assert session["json"] == {
        "AttachmentItem": {
            "attachmentType": "file",
            "name": "big.bin",
            "size": 2500,
            "contentType": "application/octet-stream",
        }
    }
    # The oversized file never rides inline as well.
    assert "attachments" not in client.posts[0]["json"]


# ---- completeness: 200 means unfinished, 201 means done ----------------------


def test_a_200_on_the_last_range_is_reported_as_incomplete_not_as_success(
    make_graph, tiny_limits, tmp_path: Path
) -> None:
    # Microsoft's contract: an intermediate PUT answers 200 OK, the PUT that
    # completes the attachment answers 201 Created. A 200 on the LAST range
    # therefore says the service is still missing bytes -- however many the local
    # counter thinks it sent -- so it must never be read as success, or the
    # recipient gets a truncated file and the tool reports ok.
    adapter, client = make_graph(
        put_hook=lambda i, start, end, total: (
            _FakeResponse({}, status_code=200) if end + 1 >= total else None
        )
    )
    big = _write(tmp_path, "big.bin", 10000)

    with pytest.raises(RuntimeError) as excinfo:
        adapter.send(
            to=["dest@example.org"], subject="Hi", body_text="hi", attachments=[big]
        )

    msg = str(excinfo.value)
    assert "never completed" in msg
    assert "201" in msg                       # names the answer it needed
    assert "big.bin" in msg
    # Above all: the message was not sent behind a truncated attachment.
    assert not any(p["url"].endswith("/send") for p in client.posts)
    assert client.deletes == [{"url": UPLOAD_URL}]


def test_next_expected_ranges_drives_the_next_offset(
    make_graph, tiny_limits, tmp_path: Path
) -> None:
    # The service commits only half of the first range and says where to resume.
    # Advancing by the local counter instead would leave bytes 2048-4095 never
    # uploaded, i.e. a hole in the middle of the delivered file.
    def hook(i: int, start: int, end: int, total: int) -> _FakeResponse | None:
        if i == 0:
            return _FakeResponse({"nextExpectedRanges": ["2048-"]}, status_code=200)
        return None

    adapter, client = make_graph(put_hook=hook)
    att = _write(tmp_path, "big.bin", 10000)

    adapter.create_draft(
        to=["dest@example.org"], subject="Hi", body_text="hi", attachments=[att]
    )

    assert _ranges(client) == [
        "bytes 0-4095/10000",
        "bytes 2048-6143/10000",   # resumed where the SERVICE asked, not at 4096
        "bytes 6144-9999/10000",
    ]
    raw = Path(att).read_bytes()
    assert client.puts[1]["content"] == raw[2048:6144]
    assert client.puts[2]["content"] == raw[6144:]


def test_a_session_that_never_advances_is_abandoned_not_looped_forever(
    make_graph, tiny_limits, tmp_path: Path
) -> None:
    # A service that keeps asking for byte 0 must not spin the uploader forever.
    adapter, client = make_graph(
        put_hook=lambda i, start, end, total: _FakeResponse(
            {"nextExpectedRanges": ["0-"]}, status_code=200
        )
    )
    big = _write(tmp_path, "big.bin", 10000)

    with pytest.raises(RuntimeError, match="stuck"):
        adapter.create_draft(
            to=["dest@example.org"], subject="Hi", body_text="hi", attachments=[big]
        )

    assert len(client.puts) <= graph_mod.MAX_UPLOAD_STALLS + 1
    assert client.deletes == [{"url": UPLOAD_URL}]


# ---- auth on the pre-authenticated upload URL --------------------------------


def test_chunk_put_carries_no_authorization_header(
    make_graph, tiny_limits, tmp_path: Path
) -> None:
    adapter, client = make_graph()
    att = _write(tmp_path, "big.bin", 2500)

    adapter.create_draft(
        to=["dest@example.org"], subject="Hi", body_text="hi", attachments=[att]
    )

    assert client.puts, "expected chunk PUTs"
    for put in client.puts:
        assert put["url"] == UPLOAD_URL
        assert not any(k.lower() == "authorization" for k in put["headers"])
        assert put["headers"]["Content-Type"] == "application/octet-stream"
        assert put["headers"]["Content-Length"] == str(len(put["content"]))
    # ...while the session-opening Graph call IS authenticated.
    session = next(p for p in client.posts if p["url"].endswith("/createUploadSession"))
    assert session["headers"]["Authorization"] == "Bearer mail-token"


def test_absolute_upload_url_bypasses_the_graph_base_url() -> None:
    # httpx leaves an absolute URL untouched by base_url, so reusing the adapter's
    # client for the off-host PUT cannot end up prefixed with /v1.0.
    client = httpx.Client(base_url=GRAPH_BASE)
    try:
        req = client.build_request(
            "PUT",
            UPLOAD_URL,
            headers={"Content-Range": "bytes 0-9/10"},
            content=b"0123456789",
        )
    finally:
        client.close()
    assert str(req.url) == UPLOAD_URL
    assert "authorization" not in {k.lower() for k in req.headers}


def test_chunk_put_gets_a_longer_timeout_than_the_json_calls(
    make_graph, tiny_limits, tmp_path: Path
) -> None:
    adapter, client = make_graph()
    att = _write(tmp_path, "big.bin", 1025)

    adapter.create_draft(
        to=["dest@example.org"], subject="Hi", body_text="hi", attachments=[att]
    )

    assert client.puts[0]["timeout"] == graph_mod.UPLOAD_CHUNK_TIMEOUT
    assert graph_mod.UPLOAD_CHUNK_TIMEOUT > 60.0


# ---- the cumulative (request-wide) guard -------------------------------------


def test_cumulative_overflow_is_refused_by_name_never_pushed_at_a_session(
    make_graph, tiny_limits, tmp_path: Path
) -> None:
    # Six files of 900 bytes each are under the 1024-byte per-file limit, so each
    # one is BELOW the upload session's minimum size: Graph answers
    # ErrorAttachmentSizeShouldNotBeLessThanMinimumSize to a session opened for
    # any of them. Their base64 cost (1200 each) still blows the 4096-byte
    # request budget after three, and since there is no second route for them the
    # only honest answer is a local refusal that names them.
    adapter, client = make_graph()
    atts = [_write(tmp_path, f"f{i}.bin", 900) for i in range(6)]

    with pytest.raises(ValueError) as excinfo:
        adapter.create_draft(
            to=["dest@example.org"], subject="Hi", body_text="hi", attachments=atts
        )

    msg = str(excinfo.value)
    for i in range(6):
        assert f"f{i}.bin" in msg          # every file is named
    assert "one message request" in msg    # ...and so is the reason
    # Nothing was created and nothing was pushed at an endpoint that would
    # refuse it: the refusal lands before any HTTP call.
    assert client.posts == []
    assert client.puts == []


def test_a_lone_file_under_the_session_minimum_still_rides_inline(
    make_graph, tmp_path: Path
) -> None:
    # PRODUCTION limits on purpose. 2,800,000 bytes is under the 3MB per-file
    # limit but costs 3,733,336 bytes encoded, which a request budget below
    # 4 MiB would have demoted to an upload session Graph refuses outright.
    # This exact payload sends today and must keep sending.
    adapter, client = make_graph()
    att = _write(tmp_path, "report.pdf", 2_800_000)

    adapter.send(
        to=["dest@example.org"], subject="Hi", body_text="hi", attachments=[att]
    )

    assert [p["url"] for p in client.posts] == ["/me/sendMail"]
    assert client.puts == []
    sent = client.posts[0]["json"]["message"]["attachments"]
    assert [a["name"] for a in sent] == ["report.pdf"]


def test_the_signature_logo_does_not_push_a_28mb_pdf_off_the_inline_route(
    make_graph, tmp_path: Path
) -> None:
    # The Numaco signature logo claims the budget first, and used to cost the PDF
    # its inline seat by 25 KB. Both still ride inline, in caller order.
    adapter, client = make_graph()
    pdf = _write(tmp_path, "offer.pdf", 2_700_000)
    logo = _write(tmp_path, "logo.png", 25_000)

    adapter.send(
        to=["dest@example.org"],
        subject="Hi",
        body_html='<p>hi</p><img src="cid:logo.png">',
        attachments=[pdf, logo],
    )

    assert [p["url"] for p in client.posts] == ["/me/sendMail"]
    sent = client.posts[0]["json"]["message"]["attachments"]
    assert [a["name"] for a in sent] == ["offer.pdf", "logo.png"]
    assert sent[1]["isInline"] is True


def test_the_two_routes_meet_exactly_at_the_per_file_limit(
    make_graph, tmp_path: Path
) -> None:
    # At the limit: inline, because a session would be refused as under-minimum.
    limit = graph_mod.INLINE_ATTACHMENT_LIMIT
    adapter, client = make_graph()
    adapter.create_draft(
        to=["dest@example.org"],
        subject="Hi",
        body_text="hi",
        attachments=[_write(tmp_path, "at-limit.bin", limit)],
    )
    assert [p["url"] for p in client.posts] == ["/me/messages"]
    assert client.puts == []

    # One byte over: a session, because inline would blow the request.
    adapter2, client2 = make_graph()
    adapter2.create_draft(
        to=["dest@example.org"],
        subject="Hi",
        body_text="hi",
        attachments=[_write(tmp_path, "over-limit.bin", limit + 1)],
    )
    session = next(
        p for p in client2.posts if p["url"].endswith("/createUploadSession")
    )
    assert session["json"]["AttachmentItem"]["size"] == limit + 1
    assert "attachments" not in client2.posts[0]["json"]


def test_everything_that_fits_stays_inline_in_caller_order(
    make_graph, tiny_limits, tmp_path: Path
) -> None:
    adapter, client = make_graph()
    atts = [_write(tmp_path, f"f{i}.bin", 500) for i in range(3)]

    adapter.create_draft(
        to=["dest@example.org"], subject="Hi", body_text="hi", attachments=atts
    )

    assert [a["name"] for a in client.posts[0]["json"]["attachments"]] == [
        "f0.bin",
        "f1.bin",
        "f2.bin",
    ]
    assert client.puts == []


def test_cid_logo_keeps_its_inline_budget_ahead_of_bulk_attachments(
    make_graph, tiny_limits, tmp_path: Path
) -> None:
    # The logo is listed LAST and claims the budget FIRST (a signature image must
    # render in the body), while the emitted payload still follows the caller's
    # order. 3 * 1200 + 88 = 3688 <= 4096, so the whole set fits.
    adapter, client = make_graph()
    bulk = [_write(tmp_path, f"f{i}.bin", 900) for i in range(3)]
    logo = _write(tmp_path, "logo.png", 64)

    adapter.create_draft(
        to=["dest@example.org"],
        subject="Hi",
        body_html='<p>hi</p><img src="cid:logo.png">',
        attachments=[*bulk, logo],
    )

    inline = client.posts[0]["json"]["attachments"]
    by_name = {a["name"]: a for a in inline}
    assert "logo.png" in by_name
    assert by_name["logo.png"]["isInline"] is True
    assert by_name["logo.png"]["contentId"] == "logo.png"
    # The inline set keeps the caller's ordering, logo last as supplied.
    assert [a["name"] for a in inline] == [*[f"f{i}.bin" for i in range(3)], "logo.png"]
    assert client.puts == []


def test_oversized_cid_attachment_stays_inline_through_the_upload_session(
    make_graph, tiny_limits, tmp_path: Path
) -> None:
    adapter, client = make_graph()
    logo = _write(tmp_path, "logo.png", 2000)  # over the per-file inline limit

    adapter.create_draft(
        to=["dest@example.org"],
        subject="Hi",
        body_html='<p>hi</p><img src="cid:logo.png">',
        attachments=[logo],
    )

    session = next(p for p in client.posts if p["url"].endswith("/createUploadSession"))
    item = session["json"]["AttachmentItem"]
    assert item["isInline"] is True
    assert item["contentId"] == "logo.png"


# ---- send: draft -> upload -> /send ------------------------------------------


def test_send_with_a_large_attachment_drafts_uploads_then_sends(
    make_graph, tiny_limits, tmp_path: Path
) -> None:
    adapter, client = make_graph()
    small = _write(tmp_path, "note.txt", 16)
    big = _write(tmp_path, "big.bin", 10000)

    adapter.send(
        to=["dest@example.org"],
        subject="Hi",
        body_text="hi",
        cc=["carbon@example.com"],
        attachments=[small, big],
    )

    urls = [p["url"] for p in client.posts]
    # /sendMail cannot carry the file, so the send is restructured.
    assert "/me/sendMail" not in urls
    assert urls == [
        "/me/messages",
        "/me/messages/draft-1/attachments/createUploadSession",
        "/me/messages/draft-1/send",
    ]
    message = client.posts[0]["json"]
    assert [r["emailAddress"]["address"] for r in message["toRecipients"]] == [
        "dest@example.org"
    ]
    assert [r["emailAddress"]["address"] for r in message["ccRecipients"]] == [
        "carbon@example.com"
    ]
    assert [a["name"] for a in message["attachments"]] == ["note.txt"]
    assert _ranges(client) == [
        "bytes 0-4095/10000",
        "bytes 4096-8191/10000",
        "bytes 8192-9999/10000",
    ]


def test_send_never_sends_when_a_chunk_fails(make_graph, tiny_limits, tmp_path: Path) -> None:
    adapter, client = make_graph(put_status=413, put_text="Request Entity Too Large")
    big = _write(tmp_path, "big.bin", 2500)

    with pytest.raises(RuntimeError) as excinfo:
        adapter.send(
            to=["dest@example.org"], subject="Hi", body_text="hi", attachments=[big]
        )

    msg = str(excinfo.value)
    assert "big.bin" in msg
    assert "413" in msg
    assert "NOT sent" in msg
    assert "draft-1" in msg
    # The send action was never reached, and the half-written session was dropped.
    assert not any(p["url"].endswith("/send") for p in client.posts)
    assert client.deletes == [{"url": UPLOAD_URL}]


def test_a_part_uploaded_draft_is_named_incomplete_with_the_missing_file(
    make_graph, tiny_limits, tmp_path: Path
) -> None:
    # contract.pdf uploads, annexes.pdf does not. A draft carrying an attachment
    # LOOKS finished in Outlook, so an error that only says "it failed" invites
    # the user to press Send and mail the customer a contract with no annexes.
    adapter, client = make_graph(session_fail_on="annexes.pdf")
    contract = _write(tmp_path, "contract.pdf", 2500)
    annexes = _write(tmp_path, "annexes.pdf", 3000)

    with pytest.raises(RuntimeError) as excinfo:
        adapter.send(
            to=["dest@example.org"],
            subject="Hi",
            body_text="hi",
            attachments=[contract, annexes],
        )

    msg = str(excinfo.value)
    assert "INCOMPLETE" in msg
    assert "annexes.pdf is NOT attached" in msg   # names what is missing
    assert "contract.pdf did upload" in msg       # ...and what is there
    assert "NOT sent" in msg
    assert "draft-1" in msg
    assert not any(p["url"].endswith("/send") for p in client.posts)


def test_a_send_graph_refused_is_reported_as_not_sent(
    make_graph, tiny_limits, tmp_path: Path
) -> None:
    # Graph answered the send with a status, so the outcome is known: nothing
    # left the mailbox and the draft is still there.
    adapter, client = make_graph(send_status=403)
    big = _write(tmp_path, "big.bin", 2500)

    with pytest.raises(RuntimeError) as excinfo:
        adapter.send(
            to=["dest@example.org"], subject="Hi", body_text="hi", attachments=[big]
        )

    msg = str(excinfo.value)
    assert "NOT sent" in msg
    assert "403" in msg               # Graph's own answer survives
    assert "still in Drafts" in msg
    assert "draft-1" in msg
    assert "UNKNOWN" not in msg


def test_a_send_that_never_answered_is_reported_as_unknown_not_as_not_sent(
    make_graph, tiny_limits, tmp_path: Path
) -> None:
    # The upload finished and POST /send went out, but no answer came back. Graph
    # may well have sent it (and moved the draft to Sent Items). Telling the user
    # "the message was NOT sent, the draft is still in Drafts" is how a customer
    # receives the same mail twice, so this case says UNKNOWN.
    adapter, client = make_graph(send_raises=httpx.ReadTimeout("timed out"))
    big = _write(tmp_path, "big.bin", 2500)

    with pytest.raises(RuntimeError) as excinfo:
        adapter.send(
            to=["dest@example.org"], subject="Hi", body_text="hi", attachments=[big]
        )

    msg = str(excinfo.value)
    assert "UNKNOWN" in msg
    assert "Sent Items" in msg
    assert "draft-1" in msg
    assert "NOT sent" not in msg   # the one claim it cannot make


def test_a_reply_whose_send_never_answered_is_also_reported_as_unknown(
    make_graph, tiny_limits, tmp_path: Path
) -> None:
    adapter, client = make_graph(send_raises=httpx.ReadTimeout("timed out"))
    big = _write(tmp_path, "big.bin", 2500)

    with pytest.raises(RuntimeError) as excinfo:
        adapter.reply("m1", body_html="<p>re</p>", attachments=[big])

    msg = str(excinfo.value)
    assert "UNKNOWN" in msg
    assert "Sent Items" in msg
    assert "NOT sent" not in msg


def test_delegate_send_guard_fires_before_any_upload(
    make_graph, tiny_limits, tmp_path: Path
) -> None:
    adapter, client = make_graph(mailbox="colleague@example.com")
    big = _write(tmp_path, "big.bin", 2500)

    with pytest.raises(RuntimeError, match="delegated mailbox"):
        adapter.send(
            to=["dest@example.org"], subject="Hi", body_text="hi", attachments=[big]
        )

    assert client.posts == []
    assert client.puts == []


def test_delegate_reply_guard_fires_before_any_upload(
    make_graph, tiny_limits, tmp_path: Path
) -> None:
    adapter, client = make_graph(mailbox="colleague@example.com")
    big = _write(tmp_path, "big.bin", 2500)

    with pytest.raises(RuntimeError, match="delegated mailbox"):
        adapter.reply("m1", body_text="hi", attachments=[big])

    assert client.posts == []
    assert client.puts == []


def test_reply_with_a_large_attachment_drafts_uploads_then_sends(
    make_graph, tiny_limits, tmp_path: Path
) -> None:
    adapter, client = make_graph()
    big = _write(tmp_path, "big.bin", 2500)

    adapter.reply("m1", body_html="<p>re</p>", attachments=[big])

    urls = [p["url"] for p in client.posts]
    # The /reply action cannot carry it either: it becomes createReply + /send.
    assert not any(u.endswith("/messages/m1/reply") for u in urls)
    assert urls == [
        "/me/messages/m1/createReply",
        "/me/messages/draft-99/attachments/createUploadSession",
        "/me/messages/draft-99/send",
    ]
    assert _ranges(client) == ["bytes 0-2499/2500"]


def test_a_big_attachment_does_not_change_who_the_reply_is_addressed_to(
    make_graph, tiny_limits, tmp_path: Path
) -> None:
    # The small path lets the /reply action address the reply, which honours a
    # Reply-To header. The large path must not quietly substitute the From
    # address, or replying to noreply@vendor.com with a 5MB log instead of a 2MB
    # one lands the reply in an unmonitored mailbox.
    adapter, client = make_graph()
    big = _write(tmp_path, "big.bin", 2500)

    adapter.reply("m1", body_html="<p>re</p>", attachments=[big])

    assert len(client.patches) == 1
    assert set(client.patches[0]["json"]) == {"body"}   # body only, no recipients
    assert client.gets == []                            # and no read() was needed


def test_reply_all_with_a_big_attachment_still_composes_the_recipient_set(
    make_graph, tiny_limits, tmp_path: Path
) -> None:
    # The other half of the same rule: when recipients DO need composing, the
    # large path composes them exactly as the small path does.
    adapter, client = make_graph()
    big = _write(tmp_path, "big.bin", 2500)

    adapter.reply("m1", body_html="<p>re</p>", reply_all=True, attachments=[big])

    patch = client.patches[0]["json"]
    assert [r["emailAddress"]["address"] for r in patch["toRecipients"]] == [
        "sender@example.org"
    ]


# ---- drafts ------------------------------------------------------------------


def test_create_reply_draft_uploads_large_and_never_sends(
    make_graph, tiny_limits, tmp_path: Path
) -> None:
    adapter, client = make_graph()
    small = _write(tmp_path, "note.txt", 16)
    big = _write(tmp_path, "big.bin", 1025)

    out = adapter.create_reply_draft(
        "m1", body_html="<p>re</p>", attachments=[small, big]
    )

    urls = [p["url"] for p in client.posts]
    assert urls == [
        "/me/messages/m1/createReply",
        "/me/messages/draft-99/attachments",          # small one, inline JSON
        "/me/messages/draft-99/attachments/createUploadSession",
    ]
    assert not any(u.endswith("/send") for u in urls)
    assert not any("sendMail" in u for u in urls)
    assert client.posts[1]["json"]["name"] == "note.txt"
    assert out["id"] == "draft-99"


def test_draft_upload_failure_names_the_draft_it_left_behind(
    make_graph, tiny_limits, tmp_path: Path
) -> None:
    # Only the send paths used to mention the stranded draft. A draft path that
    # lets the raw transport error out leaves a body-and-recipients draft in
    # Drafts that the user never hears about, and a second one on every retry.
    adapter, client = make_graph(put_status=503, put_text="Service Unavailable")
    big = _write(tmp_path, "big.bin", 2500)

    with pytest.raises(RuntimeError) as excinfo:
        adapter.create_draft(
            to=["dest@example.org"], subject="Hi", body_text="hi", attachments=[big]
        )

    msg = str(excinfo.value)
    assert "draft-1" in msg            # the orphan is named
    assert "still in Drafts" in msg
    assert "big.bin" in msg
    assert "INCOMPLETE" in msg
    assert client.deletes == [{"url": UPLOAD_URL}]


def test_reply_draft_upload_failure_names_the_draft_it_left_behind(
    make_graph, tiny_limits, tmp_path: Path
) -> None:
    adapter, client = make_graph(put_status=503, put_text="Service Unavailable")
    big = _write(tmp_path, "big.bin", 2500)

    with pytest.raises(RuntimeError) as excinfo:
        adapter.create_reply_draft("m1", body_html="<p>re</p>", attachments=[big])

    msg = str(excinfo.value)
    assert "draft-99" in msg
    assert "still in Drafts" in msg
    assert "big.bin" in msg


def test_reply_upload_failure_says_not_sent_and_names_the_threaded_draft(
    make_graph, tiny_limits, tmp_path: Path
) -> None:
    # reply()'s large path builds a threaded draft first. If the upload dies
    # there, the send authorization has already been spent, so the user has to be
    # told both that nothing was sent and that a draft is waiting.
    adapter, client = make_graph(put_status=503, put_text="Service Unavailable")
    big = _write(tmp_path, "big.bin", 2500)

    with pytest.raises(RuntimeError) as excinfo:
        adapter.reply("m1", body_html="<p>re</p>", attachments=[big])

    msg = str(excinfo.value)
    assert "NOT sent" in msg
    assert "draft-99" in msg
    assert "big.bin" in msg
    assert not any(p["url"].endswith("/send") for p in client.posts)


def test_delegate_draft_refuses_a_large_attachment_before_creating_anything(
    make_graph, tiny_limits, tmp_path: Path
) -> None:
    # Microsoft: "With delegated permissions, createUploadSession succeeds only
    # if the message or event is in the signed-in user's mailbox" -- a delegated
    # mailbox gets HTTP 403 with no workaround. Opening the session anyway would
    # strand a body-and-recipients draft with no attachment in someone else's
    # mailbox, so the refusal comes before the draft exists.
    adapter, client = make_graph(mailbox="colleague@example.com")
    big = _write(tmp_path, "big.bin", 2500)

    with pytest.raises(RuntimeError) as excinfo:
        adapter.create_draft(
            to=["dest@example.org"], subject="Hi", body_text="hi", attachments=[big]
        )

    msg = str(excinfo.value)
    assert "colleague@example.com" in msg
    assert "403" in msg
    assert "big.bin" in msg
    assert client.posts == []  # no draft was created
    assert client.puts == []


def test_delegate_reply_draft_refuses_a_large_attachment_before_creating_anything(
    make_graph, tiny_limits, tmp_path: Path
) -> None:
    adapter, client = make_graph(mailbox="colleague@example.com")
    big = _write(tmp_path, "big.bin", 2500)

    with pytest.raises(RuntimeError, match="delegated mailbox"):
        adapter.create_reply_draft("m1", body_html="<p>re</p>", attachments=[big])

    assert client.posts == []
    assert client.patches == []
    assert client.puts == []


def test_delegate_draft_with_only_small_attachments_still_works(
    make_graph, tiny_limits, tmp_path: Path
) -> None:
    # The guard is about upload sessions only: a delegated draft that needs none
    # still targets /users/{mailbox} with the shared token, as it always has.
    adapter, client = make_graph(mailbox="colleague@example.com")
    small = _write(tmp_path, "note.txt", 16)

    adapter.create_draft(
        to=["dest@example.org"], subject="Hi", body_text="hi", attachments=[small]
    )

    assert [p["url"] for p in client.posts] == ["/users/colleague@example.com/messages"]
    assert client.posts[0]["headers"]["Authorization"] == "Bearer shared-token"
    assert client.puts == []


# ---- errors ------------------------------------------------------------------


def test_attachment_beyond_the_graph_ceiling_names_file_size_and_limit(
    make_graph, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    adapter, client = make_graph()
    monkeypatch.setattr(graph_mod, "MAX_ATTACHMENT_SIZE", 2 * 1024 * 1024)
    huge = _write(tmp_path, "huge.bin", 3 * 1024 * 1024)

    with pytest.raises(ValueError, match="caps a single mail attachment") as excinfo:
        adapter.create_draft(
            to=["dest@example.org"], subject="Hi", body_text="hi", attachments=[huge]
        )

    msg = str(excinfo.value)
    assert "huge.bin" in msg          # names the file
    assert "3.0MB" in msg             # names its size
    assert "2MB" in msg               # names the real limit
    assert "not implemented" not in msg.lower()
    assert client.posts == []         # refused before any HTTP call


def test_missing_attachment_still_raises_before_any_http_call(
    make_graph, tmp_path: Path
) -> None:
    adapter, client = make_graph()

    with pytest.raises(FileNotFoundError, match="Attachment not found"):
        adapter.create_draft(
            to=["dest@example.org"],
            subject="Hi",
            body_text="hi",
            attachments=[str(tmp_path / "ghost.txt")],
        )

    assert client.posts == []


def test_a_202_is_not_a_completion_signal_either(
    make_graph, tiny_limits, tmp_path: Path
) -> None:
    # This endpoint does not document 202 at all; it is tolerated as "more
    # expected" so a proxy that emits one is not mistaken for a failure, but it
    # can never stand in for the 201 Created that means the attachment is
    # assembled. A run that ends on 202 is an unfinished upload.
    adapter, client = make_graph(put_status=202)
    big = _write(tmp_path, "big.bin", 1025)

    with pytest.raises(RuntimeError, match="never completed"):
        adapter.create_draft(
            to=["dest@example.org"], subject="Hi", body_text="hi", attachments=[big]
        )

    assert client.deletes == [{"url": UPLOAD_URL}]


def test_refused_upload_session_names_the_file_and_graphs_reason(
    make_graph, tiny_limits, tmp_path: Path
) -> None:
    adapter, client = make_graph(
        session_status=403, session_text='{"error":{"code":"ErrorAccessDenied"}}'
    )
    big = _write(tmp_path, "big.bin", 2500)

    with pytest.raises(RuntimeError) as excinfo:
        adapter.create_draft(
            to=["dest@example.org"], subject="Hi", body_text="hi", attachments=[big]
        )

    msg = str(excinfo.value)
    assert "big.bin" in msg
    assert "403" in msg
    assert "ErrorAccessDenied" in msg  # Graph's own reason survives, unlike
    assert client.puts == []           # raise_for_status, which would drop it


def test_missing_upload_url_is_reported(make_graph, tiny_limits, tmp_path: Path) -> None:
    adapter, client = make_graph()
    big = _write(tmp_path, "big.bin", 1025)

    def _no_url(url: str, **kwargs: Any) -> _FakeResponse:
        client.posts.append({"url": url, "json": kwargs.get("json"), "headers": {}})
        if url.endswith("/createUploadSession"):
            return _FakeResponse({})
        return _FakeResponse({"id": "draft-1", "webLink": "w", "isDraft": True})

    adapter._client.post = _no_url  # type: ignore[method-assign]

    with pytest.raises(RuntimeError, match="no upload session"):
        adapter.create_draft(
            to=["dest@example.org"], subject="Hi", body_text="hi", attachments=[big]
        )

    assert client.puts == []


def test_adapter_no_longer_claims_the_feature_is_unimplemented() -> None:
    source = Path(graph_mod.__file__).read_text()
    assert "not implemented in this phase" not in source
