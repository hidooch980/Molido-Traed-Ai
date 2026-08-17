"""MolidoTrade AI backend.

The version is a claim about what this deployment can do, so it moves when that
changes rather than on a schedule.

0.2.0 - the release where the platform could first place an order.

  Before this, `api_can_place_orders` was false, the only broker adapter was a
  simulator that fills nothing, and the MQL5 bridge had no OrderSend in it -
  while the autopilot reported `would_send_live_orders: true`, which was a
  policy verdict about a path that did not exist. It now sends real orders to
  the terminal, at most once each, behind four gates, and one has filled.

  Also in this release, and each one was a caption that had stopped being true:
  the broker's clock was read three hours out and is now measured rather than
  assumed; the accounts route said no adapter existed long after one did; and
  eighteen read routes answered anonymously on a deployment that had asked for
  a key.

0.1.0 - everything that reads, measures and refuses to conclude.
"""

__version__ = "0.2.0"
