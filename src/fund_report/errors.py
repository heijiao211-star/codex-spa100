class FundReportError(Exception):
    """Base class for expected report failures."""


class SourceUnavailableError(FundReportError):
    """A source could not be reached or did not return usable content."""


class ParseError(FundReportError):
    """A source response does not match the supported parser contract."""


class SourceConflictError(FundReportError):
    """Independent sources returned conflicting values for the same field."""


class StaleDataError(FundReportError):
    """The latest official NAV is older than the configured tolerance."""


class InsufficientHistoryError(FundReportError):
    """There are not enough official NAV observations for a requested metric."""

