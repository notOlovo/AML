"""Claude writes the case note; the rules and the score decide without it.

The public surface is small on purpose, and it is what the UI and the command
line call: `template` for the deterministic note, `claude` for the model's one,
`verify` for the number check that runs over whatever the model wrote.
"""

from ..config import MODELS, PRICE
from .bedrock import note as claude
from .facts import facts, template
from .prompt import SYSTEM
from .verify import numbers, verify

__all__ = ["MODELS", "PRICE", "SYSTEM", "claude", "facts", "numbers", "template", "verify"]
