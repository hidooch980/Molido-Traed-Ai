"""Deterministic analyzers for the agent roles (stage 6). Shadow only.

Every analyzer takes an `AnalysisContext` that already holds only the bars
that had *closed* at `as_of`, and returns an `AgentMessage`. Nothing here
places, sizes or authorises an order; Rocket signals are PROPOSED records.
"""
