from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class RetryPolicy:
    max_attempts: int = 3
    backoff_seconds: list[float] = field(default_factory=lambda: [1.0, 2.0, 5.0])

    def backoff_for(self, attempt_index: int) -> float:
        if not self.backoff_seconds:
            return 0.0
        if attempt_index < len(self.backoff_seconds):
            return self.backoff_seconds[attempt_index]
        return self.backoff_seconds[-1]
