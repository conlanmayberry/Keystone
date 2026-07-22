from __future__ import annotations

from megachud.models.conversation import Conversation, ConversationMessage
from megachud.models.task import Task, TaskStatus


def test_conversation_roundtrip(db_session):
    conversation = Conversation()
    db_session.add(conversation)
    db_session.commit()

    fetched = db_session.get(Conversation, conversation.id)
    assert fetched is not None
    assert fetched.created_at is not None
    assert fetched.agent_id is None
    assert fetched.project_name is None


def test_conversation_message_roundtrip(db_session):
    conversation = Conversation()
    db_session.add(conversation)
    db_session.commit()

    message = ConversationMessage(conversation_id=conversation.id, role="user", content="fetch example.com")
    db_session.add(message)
    db_session.commit()

    fetched = db_session.get(ConversationMessage, message.id)
    assert fetched.role == "user"
    assert fetched.content == "fetch example.com"
    assert fetched.linked_task_id is None
    assert fetched.proposed_plan_json is None
    assert fetched.plan_status is None
    assert fetched.execution_mode is None


def test_conversation_message_with_proposed_plan_and_linked_task(db_session):
    conversation = Conversation()
    db_session.add(conversation)
    db_session.commit()

    task = Task(title="t", prompt="p", status=TaskStatus.PENDING)
    db_session.add(task)
    db_session.commit()

    message = ConversationMessage(
        conversation_id=conversation.id,
        role="assistant",
        content="Here's the plan",
        proposed_plan_json='[{"tool_name": "http_fetch", "args": {"url": "https://example.com"}}]',
        plan_status="pending",
        execution_mode="semi_manual",
        linked_task_id=None,
    )
    db_session.add(message)
    db_session.commit()

    fetched = db_session.get(ConversationMessage, message.id)
    assert fetched.plan_status == "pending"
    assert fetched.execution_mode == "semi_manual"
    assert fetched.linked_task_id is None

    fetched.linked_task_id = task.id
    fetched.plan_status = "approved"
    db_session.commit()

    refetched = db_session.get(ConversationMessage, message.id)
    assert refetched.linked_task_id == task.id
    assert refetched.plan_status == "approved"
