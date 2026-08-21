"""AI 辅助生成服务测试。"""

from __future__ import annotations

import json
import os
from unittest.mock import AsyncMock, patch

import pytest

from app import ai_service
from app.dsl import ChatScene, VideoDSL
from app.models import Message, Participant


@pytest.fixture(autouse=True)
def reset_quota():
    """每个测试前清空内存配额,避免相互影响。"""
    ai_service._quota.clear()
    yield
    ai_service._quota.clear()


def make_scene(**overrides) -> ChatScene:
    participants = [
        Participant(id="p1", name="Alice", avatar_url=None, persona="乐观的创业者"),
        Participant(id="p2", name="Bob", avatar_url=None, persona="谨慎的工程师"),
    ]
    messages = [
        Message(sender_id="p1", kind="text", text="在吗", delay_ms=1500),
        Message(sender_id="p2", kind="text", text="在的", delay_ms=1500),
    ]
    base = dict(
        mode="single",
        participants=participants,
        messages=messages,
        intent="short_video_drama",
        intent_acknowledged=True,
    )
    base.update(overrides)
    return ChatScene(**base)


# ---------- JSON 抽取 ----------


def test_extract_json_block_from_markdown():
    text = '```json\n{"title": "test"}\n```'
    assert ai_service._extract_json_block(text) == '{"title": "test"}'


def test_extract_json_block_without_language_tag():
    text = '```\n{"title": "test"}\n```'
    assert ai_service._extract_json_block(text) == '{"title": "test"}'


def test_extract_json_block_bare_json():
    text = 'some text\n{"title": "test"}\nmore text'
    assert ai_service._extract_json_block(text) == '{"title": "test"}'


def test_extract_json_block_no_json_raises():
    with pytest.raises(ai_service.AIServiceError) as exc_info:
        ai_service._extract_json_block("just plain text")
    assert exc_info.value.code == "parse_error"


# ---------- 配额 ----------


def test_quota_initially_full():
    ai_service.AI_DAILY_LIMIT = 10
    assert ai_service._check_quota("u1") == 10


def test_quota_consumes_and_limits():
    ai_service.AI_DAILY_LIMIT = 2
    assert ai_service._check_quota("u1") == 2
    ai_service._consume_quota("u1")
    assert ai_service._check_quota("u1") == 1
    ai_service._consume_quota("u1")
    with pytest.raises(ai_service.AIServiceError) as exc_info:
        ai_service._check_quota("u1")
    assert exc_info.value.code == "quota_exceeded"


def test_quota_status_format():
    ai_service.AI_DAILY_LIMIT = 5
    ai_service._consume_quota("u2")
    status = ai_service.get_quota_status("u2")
    assert status["daily_limit"] == 5
    assert status["used_today"] == 1
    assert status["remaining_today"] == 4


# ---------- DSL 合并 ----------


def test_merge_generated_creates_valid_dsl():
    scene = make_scene()
    participants_data = [
        {"id": "p1", "name": "Alice"},
        {"id": "p2", "name": "Bob"},
    ]
    messages_data = [
        {"sender_id": "p1", "kind": "text", "text": "你好", "delay_ms": 1500},
        {"sender_id": "p2", "kind": "text", "text": "你好呀", "delay_ms": 1200},
    ]
    dsl = ai_service._merge_generated(scene, participants_data, messages_data)
    assert dsl.scene.title == scene.title
    assert len(dsl.scene.participants) == 2
    assert len(dsl.scene.messages) == 2
    assert dsl.template == scene.style_theme


def test_merge_generated_fixes_invalid_reply_to():
    scene = make_scene(mode="group")
    participants_data = [{"id": "p1", "name": "Alice"}, {"id": "p2", "name": "Bob"}]
    messages_data = [
        {"sender_id": "p1", "kind": "text", "text": "第一条", "delay_ms": 1500},
        {"sender_id": "p2", "kind": "text", "text": "第二条", "delay_ms": 1500, "reply_to": 5},
    ]
    dsl = ai_service._merge_generated(scene, participants_data, messages_data)
    assert dsl.scene.messages[1].reply_to is None


def test_merge_generated_rejects_high_risk_content():
    scene = make_scene()
    participants_data = [{"id": "p1", "name": "Alice"}]
    messages_data = [
        {"sender_id": "p1", "kind": "text", "text": "转账给我", "delay_ms": 1500},
    ]
    with pytest.raises(Exception):  # Pydantic ValidationError
        ai_service._merge_generated(scene, participants_data, messages_data)


# ---------- generate_dialogue (mock LLM) ----------


@pytest.mark.asyncio
async def test_generate_dialogue_success(monkeypatch):
    ai_service.AI_DAILY_LIMIT = 10
    ai_service.AI_API_KEY = "sk-test"

    async def fake_completion(*args, **kwargs):
        content = json.dumps(
            {
                "title": "AI 生成的测试对话",
                "participants": [
                    {"id": "p1", "name": "小明", "persona": "活泼"},
                    {"id": "p2", "name": "小红", "persona": "文静"},
                ],
                "messages": [
                    {"sender_id": "p1", "kind": "text", "text": "周末去爬山吗？", "delay_ms": 1500},
                    {"sender_id": "p2", "kind": "text", "text": "好啊！", "delay_ms": 1200},
                ],
            },
            ensure_ascii=False,
        )
        return ai_service.LLMResponse(content=content, model="gpt-test", usage={})

    monkeypatch.setattr(ai_service, "_chat_completion", fake_completion)

    dsl = await ai_service.generate_dialogue(
        user_id="u1",
        synopsis="两个朋友商量周末计划",
        mode="single",
        style_theme="comic",
        intent="short_video_drama",
        num_messages=4,
    )
    assert dsl.scene.title == "AI 生成的测试对话"
    assert len(dsl.scene.participants) == 2
    assert len(dsl.scene.messages) == 2
    assert dsl.scene.messages[0].text == "周末去爬山吗？"


@pytest.mark.asyncio
async def test_generate_dialogue_not_configured():
    ai_service.AI_API_KEY = ""
    with pytest.raises(ai_service.AIServiceError) as exc_info:
        await ai_service.generate_dialogue("u1", " synopsis")
    assert exc_info.value.code == "not_configured"


@pytest.mark.asyncio
async def test_generate_dialogue_quota_exceeded(monkeypatch):
    ai_service.AI_DAILY_LIMIT = 1
    ai_service.AI_API_KEY = "sk-test"
    ai_service._consume_quota("u1")

    with pytest.raises(ai_service.AIServiceError) as exc_info:
        await ai_service.generate_dialogue("u1", "synopsis")
    assert exc_info.value.code == "quota_exceeded"


@pytest.mark.asyncio
async def test_generate_dialogue_bad_json(monkeypatch):
    ai_service.AI_DAILY_LIMIT = 10
    ai_service.AI_API_KEY = "sk-test"

    async def fake_completion(*args, **kwargs):
        return ai_service.LLMResponse(content="不是 JSON", model="gpt-test", usage={})

    monkeypatch.setattr(ai_service, "_chat_completion", fake_completion)

    with pytest.raises(ai_service.AIServiceError) as exc_info:
        await ai_service.generate_dialogue("u1", "synopsis")
    assert exc_info.value.code == "parse_error"


# ---------- continue_dialogue (mock LLM) ----------


@pytest.mark.asyncio
async def test_continue_dialogue_success(monkeypatch):
    ai_service.AI_DAILY_LIMIT = 10
    ai_service.AI_API_KEY = "sk-test"

    async def fake_completion(*args, **kwargs):
        content = json.dumps(
            {
                "candidates": [
                    {"sender_id": "p1", "kind": "text", "text": "候选一", "delay_ms": 1500},
                    {"sender_id": "p2", "kind": "text", "text": "候选二", "delay_ms": 1500},
                ]
            },
            ensure_ascii=False,
        )
        return ai_service.LLMResponse(content=content, model="gpt-test", usage={})

    monkeypatch.setattr(ai_service, "_chat_completion", fake_completion)

    scene = make_scene()
    candidates = await ai_service.continue_dialogue("u1", scene, num_candidates=3)
    assert len(candidates) == 2
    assert candidates[0].text == "候选一"


@pytest.mark.asyncio
async def test_continue_dialogue_empty_context():
    ai_service.AI_DAILY_LIMIT = 10
    ai_service.AI_API_KEY = "sk-test"
    # 用 model_construct 构造空消息场景,绕过 Pydantic min_length 校验
    empty_scene = ChatScene.model_construct(
        mode="group",
        title="空对话",
        background="#ffffff",
        background_image_url=None,
        duration_ms=None,
        opacity=1.0,
        style_theme="comic",
        intent="short_video_drama",
        intent_acknowledged=True,
        participants=[Participant(id="p1", name="Alice")],
        messages=[],
    )
    with pytest.raises(ai_service.AIServiceError) as exc_info:
        await ai_service.continue_dialogue("u1", empty_scene)
    assert exc_info.value.code == "empty_context"


# ---------- 端点测试 ----------


@pytest.fixture
def client():
    from fastapi.testclient import TestClient
    from app.main import app

    return TestClient(app)


@pytest.mark.skipif(not os.getenv("CI"), reason="端点测试需要完整 app 上下文")
def test_quota_endpoint(client):
    resp = client.get("/api/ai/quota", headers={"X-User-Id": "testuser"})
    assert resp.status_code == 200
    data = resp.json()
    assert "daily_limit" in data
    assert "remaining_today" in data


def test_health_endpoint_unconfigured(client):
    """未配置 AI_API_KEY 时 /api/ai/health 返回 configured:false。"""
    with patch.object(ai_service, "AI_API_KEY", ""):
        resp = client.get("/api/ai/health")
        assert resp.status_code == 200
        data = resp.json()
        assert data["configured"] is False
        assert data["reachable"] is False


@pytest.mark.asyncio
async def test_check_ai_connection_not_configured():
    with patch.object(ai_service, "AI_API_KEY", ""):
        result = await ai_service.check_ai_connection()
        assert result["configured"] is False


@pytest.mark.asyncio
async def test_chat_completion_connect_error(monkeypatch):
    """_chat_completion 应把 httpx.ConnectError 转换为 connect_error 并给出排查提示。"""
    ai_service.AI_API_KEY = "sk-test"

    import httpx

    async def fake_post(*args, **kwargs):
        raise httpx.ConnectError("All connection attempts failed")

    monkeypatch.setattr(httpx.AsyncClient, "post", fake_post)

    with pytest.raises(ai_service.AIServiceError) as exc_info:
        await ai_service._chat_completion([{"role": "user", "content": "hi"}])
    assert exc_info.value.code == "connect_error"
    assert "host.docker.internal" in str(exc_info.value)
