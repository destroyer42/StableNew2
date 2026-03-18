class PromptOptimizerError(Exception):
    """Base optimizer error."""


class PromptSplitError(PromptOptimizerError):
    """Raised when prompt chunk splitting fails."""


class PromptClassificationError(PromptOptimizerError):
    """Raised when classification fails."""


class PromptConfigError(PromptOptimizerError):
    """Raised for invalid optimizer configuration."""
