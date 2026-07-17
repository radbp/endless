"""The Arq background worker — same codebase, separate process.

Drains the transactional outbox (Stripe, email), runs the reservation-expiry
sweep, and handles abandoned-cart jobs. Wired in F0.6; jobs land with the
modules that need them.
"""
