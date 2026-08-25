"""Commerce-specific exceptions."""

class CommerceError(RuntimeError):
    pass

class PackageBuildError(CommerceError):
    pass

class ConfigurationError(CommerceError):
    pass

class PublishError(CommerceError):
    pass

# Backwards-compatible internal name used by the HTTP transport.
CommercePublishError = PublishError
