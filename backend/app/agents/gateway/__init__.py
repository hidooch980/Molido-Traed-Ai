"""Grok Gateway: the one door every agent's language-model request goes through.

Advisory only. Nothing on the decision, risk or execution path imports this
package. With no `XAI_API_KEY` in the environment the gateway is disabled and
every request returns DISABLED, which the advisor turns into ABSTAIN - and an
abstaining council produces WAIT, never a trade.
"""
