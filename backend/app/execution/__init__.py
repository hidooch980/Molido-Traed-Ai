"""Execution layer (spec phases 25-27).

Nothing in this package can reach a live broker: the only adapter is a
simulator. A real one is a separate module whose credentials the operator
supplies on the server.
"""
