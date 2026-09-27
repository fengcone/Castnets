from uuid import uuid4

from .content import context_at, now
from .models import Branch, DomainError, Turn, data, integer, nonblank
from .provider import AnswerProvider, MockProvider
from .storage import Store


class Service:
    def __init__(self, store: Store, provider: AnswerProvider | None = None):
        self.store = store
        self.provider = provider or MockProvider()

    def make_turn(self, episode_id, anchor_ms, question):
        question = nonblank(question, "question")
        episode = self.store.get("episodes", episode_id)
        try:
            content = self.store.get("content", episode_id)
        except DomainError as error:
            if error.code != "not_found":
                raise
            content = None
        context = context_at(episode, content, anchor_ms, question)
        return Turn(str(uuid4()), question, self.provider.answer(question, context), context, now())

    def create_branch(self, episode_id, anchor_ms, question, resume_offset_ms=5000):
        nonblank(episode_id, "episode_id", 200)
        integer(anchor_ms, "anchor_ms")
        integer(resume_offset_ms, "resume_offset_ms", maximum=30000)
        episode = self.store.get("episodes", episode_id)
        if episode["duration_ms"] is not None and anchor_ms > episode["duration_ms"]:
            raise DomainError("anchor_ms exceeds episode duration")
        turn = self.make_turn(episode_id, anchor_ms, question)
        branch = data(Branch("1.0", str(uuid4()), episode_id, anchor_ms, resume_offset_ms,
                             max(0, anchor_ms - resume_offset_ms), "active", [turn], now(), None))
        self.store.put("branches", branch["id"], branch)
        return branch

    def add_turn(self, branch_id, question):
        # Read-check-write in one transaction prevents append/resume races and lost turns.
        with self.store.connection() as db:
            db.execute("BEGIN IMMEDIATE")
            branch = self.store.get("branches", branch_id, db)
            if branch["state"] != "active":
                raise DomainError("Branch has already resumed", "branch_closed", 409)
            branch["turns"].append(data(self.make_turn(branch["episode_id"], branch["anchor_ms"], question)))
            self.store.put("branches", branch_id, branch, db)
            return branch

    def resume(self, branch_id):
        with self.store.connection() as db:
            db.execute("BEGIN IMMEDIATE")
            branch = self.store.get("branches", branch_id, db)
            if branch["state"] == "active":
                branch["state"] = "resumed"
                branch["resumed_at"] = now()
                self.store.put("branches", branch_id, branch, db)
            return branch
