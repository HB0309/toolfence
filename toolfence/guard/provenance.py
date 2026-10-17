"""Provenance tracking for Guard (GRD-4, GRD-6).

``ProvenanceStore`` records where values come from and resolves argument provenance.

Priority order (GRD-4)
-----------------------
1. ``"user"``        — value appeared verbatim in the user's inbound message this session.
2. ``"first-party"`` — value appeared in a result from a first-party tool.
3. ``"untrusted"``   — value appeared in a result from an untrusted tool, OR cannot be
                       traced to any source (fail-closed default).

Normalisation (GRD-4)
----------------------
Comparison is done on *normalised* forms of values so that minor formatting differences
do not cause a provenance miss:

* Whitespace-collapse: ``" ".join(str(v).split())`` — collapses all internal whitespace
  and strips leading/trailing whitespace.
* Numeric string ↔ int matching: the string ``"1"`` matches the integer ``1`` and
  vice versa.  This handles the common case where an ID returned as a JSON number is
  later used as a string argument (or vice versa).

File-label inheritance (GRD-6)
--------------------------------
When nanobot saves a large result to a workspace file, the caller records the path with
the result's trust label via ``record_file_path``.  When a later tool call reads that
path as an argument, ``resolve_argument`` finds the stored label and returns it.
"""

from __future__ import annotations

from typing import Any

from toolfence.contracts.trace import ProvenanceLabel


# JSON punctuation characters stripped from token boundaries when extracting
# values from tool results.  This lets "Alice" in '{"name": "Alice"}' be
# stored and matched as the bare string "Alice".
_JSON_STRIP_CHARS = '{}[]",: \t\r\n'

# Extra punctuation stripped from user-message tokens beyond _JSON_STRIP_CHARS.
# Covers sentence-ending periods and bracket/parenthesis wrapping so that
# "(alice@example.com)." and "report.txt." resolve to their bare forms.
_USER_STRIP_CHARS = _JSON_STRIP_CHARS + "()."


def _normalise(value: Any) -> set[str]:
    """Return the set of normalised string forms used for provenance matching.

    Always produces a non-empty set.  Two forms are included:
    * The whitespace-collapsed string representation.
    * If the value is a pure-decimal string (or an int/float), also include the
      equivalent integer string so ``"1"`` ↔ ``1`` ↔ ``1.0`` all match.
    """
    collapsed = " ".join(str(value).split())
    forms: set[str] = {collapsed}

    # Add numeric normalisation: "1" → "1", 1 → "1", 1.0 → "1"
    try:
        as_int = str(int(float(collapsed)))
        forms.add(as_int)
    except (ValueError, TypeError):
        pass

    return forms


def _extract_tokens(text: str) -> list[str]:
    """Extract provenance-matchable tokens from a result string.

    Splits on whitespace first, then strips JSON punctuation from each token so
    that values embedded in JSON structures (e.g. ``'{"name": "Alice"}'``) are
    stored as their bare forms (``"Alice"``).  The original whitespace-collapsed
    full string is also included so multi-word phrases can be matched exactly.
    """
    tokens: list[str] = []
    # Full collapsed string first (for exact multi-word phrase matching).
    collapsed = " ".join(text.split())
    if collapsed:
        tokens.append(collapsed)
    # Individual tokens, stripped of JSON punctuation on both sides.
    for raw in text.split():
        stripped = raw.strip(_JSON_STRIP_CHARS)
        if stripped:
            tokens.append(stripped)
            # Also add the un-stripped form in case the caller stored it that way.
            if stripped != raw:
                tokens.append(raw)
    return tokens


class ProvenanceStore:
    """Session-scoped store that tracks value origins for provenance resolution.

    Create one instance per evaluation session (or per nanobot turn session).
    All ``record_*`` methods accumulate; nothing is cleared within a session.
    """

    def __init__(self) -> None:
        # Maps normalised string form → provenance label.
        # "user" values are stored separately so priority resolution is explicit.
        self._user_values: set[str] = set()
        # Full collapsed user message texts — used for multi-word substring lookup.
        self._user_messages: list[str] = []
        # label can be "first-party" or "untrusted"
        self._tool_values: dict[str, ProvenanceLabel] = {}
        # Full collapsed tool result texts with their labels — for multi-word substring lookup.
        self._tool_texts: list[tuple[str, ProvenanceLabel]] = []
        # file path → provenance label (GRD-6)
        self._file_labels: dict[str, ProvenanceLabel] = {}

    # ------------------------------------------------------------------
    # Recording methods
    # ------------------------------------------------------------------

    def record_user_message(self, text: str) -> None:
        """Record all whitespace-token substrings from the user's inbound message.

        Every whitespace-separated token in *text* is normalised and stored as a
        user-sourced value so that names/IDs the user typed are always resolved as
        ``"user"`` provenance (GRD-4 rule 1).

        The full collapsed message is also stored so that multi-word sub-phrases
        (e.g. ``"Harsh Bhaskar"`` extracted from ``"Book for Harsh Bhaskar"``)
        can be matched via substring search when the exact token lookup misses.

        Parameters
        ----------
        text:
            The full text of the user's inbound message.
        """
        # Store every individual token as well as the full collapsed string.
        collapsed = " ".join(text.split())
        if collapsed:
            self._user_values.add(collapsed)
            # Keep the full message for multi-word substring fallback.
            self._user_messages.append(collapsed)
        for token in text.split():
            norm = " ".join(token.split())
            if norm:
                self._user_values.add(norm)
                # Strip sentence/bracket punctuation so that tokens like
                # "(alice@example.com)." and "report.txt." are also stored as
                # their bare forms "alice@example.com" and "report.txt".
                stripped = norm.strip(_USER_STRIP_CHARS)
                if stripped and stripped != norm:
                    self._user_values.add(stripped)
                # Also add numeric forms so "1" matches user-typed "1"
                try:
                    self._user_values.add(str(int(float(norm))))
                except (ValueError, TypeError):
                    pass

    def record_tool_result(
        self,
        tool_name: str,
        result: str,
        label: ProvenanceLabel,
    ) -> None:
        """Record every whitespace-collapsed token from a tool result.

        Parameters
        ----------
        tool_name:
            The tool that produced the result (not used for lookups; kept for
            future audit logging).
        result:
            The raw result string returned by the tool.
        label:
            The trust label of the tool from ``surface.json`` (``"first-party"`` or
            ``"untrusted"``).
        """
        # Extract all matchable tokens from the result (JSON-punctuation-stripped)
        # and store each under its normalised forms.
        for token in _extract_tokens(result):
            norm = " ".join(token.split())
            if norm:
                self._store_tool_value(norm, label)
                try:
                    self._store_tool_value(str(int(float(norm))), label)
                except (ValueError, TypeError):
                    pass
        # Keep the full collapsed result text for multi-word substring fallback.
        collapsed_result = " ".join(result.split())
        if collapsed_result:
            self._tool_texts.append((collapsed_result, label))

    def record_file_path(self, path: str, label: ProvenanceLabel) -> None:
        """Record a workspace file path with its trust label (GRD-6).

        Parameters
        ----------
        path:
            Absolute or relative path of the workspace file.
        label:
            The trust label inherited from the tool result that was saved there.
        """
        self._file_labels[path] = label

    # ------------------------------------------------------------------
    # Resolution
    # ------------------------------------------------------------------

    def resolve_argument(self, value: Any) -> ProvenanceLabel:
        """Return the provenance label for *value* (GRD-4 priority order).

        Priority:
        1. ``"user"`` if any normalised form of *value* is in the user-message store.
        2. ``"first-party"`` if any normalised form is in the tool-result store with
           label ``"first-party"``.
        3. ``"untrusted"`` if any normalised form is in the tool-result store with
           label ``"untrusted"``.
        4. File-path lookup: if *value* (as a string) is a known file path, return
           its stored label.
        5. ``"untrusted"`` for any value that cannot be traced (fail-closed, GRD-4).

        Parameters
        ----------
        value:
            The raw argument value to resolve.

        Returns
        -------
        ProvenanceLabel
        """
        forms = _normalise(value)

        # Priority 1 — user source always wins.
        if forms & self._user_values:
            return "user"

        # Priority 2 & 3 — check tool-result store; prefer first-party over untrusted.
        found_label: ProvenanceLabel | None = None
        for form in forms:
            stored = self._tool_values.get(form)
            if stored == "first-party":
                return "first-party"
            if stored == "untrusted":
                found_label = "untrusted"

        if found_label is not None:
            return found_label

        # Priority 4 — file-path label inheritance (GRD-6).
        str_value = str(value)
        if str_value in self._file_labels:
            return self._file_labels[str_value]

        # Priority 5 — multi-word substring fallback.
        # If the queried value contains a space it may be a sub-phrase (e.g. a full
        # name) that was never stored as an exact token.  Search the full stored
        # message/result texts in priority order.
        collapsed_value = " ".join(str(value).split())
        if " " in collapsed_value:
            for msg in self._user_messages:
                if collapsed_value in msg:
                    return "user"
            for text, lbl in self._tool_texts:
                if collapsed_value in text and lbl == "first-party":
                    return "first-party"
            for text, lbl in self._tool_texts:
                if collapsed_value in text and lbl == "untrusted":
                    return "untrusted"

        # Priority 6 — fail-closed default.
        return "untrusted"

    def resolve_file_path(self, path: str) -> ProvenanceLabel | None:
        """Return the stored label for *path*, or ``None`` if not recorded (GRD-6).

        Separate from ``resolve_argument`` so callers can distinguish between
        "path has a stored label" and "path happens to look like a known value".
        """
        return self._file_labels.get(path)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _store_tool_value(self, norm: str, label: ProvenanceLabel) -> None:
        """Store *norm* → *label*, keeping the higher-trust label on conflict.

        ``"first-party"`` is higher trust than ``"untrusted"``: if a value was
        already recorded as ``"first-party"`` we do not downgrade it to
        ``"untrusted"`` from a later untrusted result.
        """
        existing = self._tool_values.get(norm)
        if existing is None or existing == "untrusted":
            # No existing entry, or existing is lower-trust — store/upgrade.
            self._tool_values[norm] = label
        # If existing == "first-party" and new label == "untrusted", keep first-party.
